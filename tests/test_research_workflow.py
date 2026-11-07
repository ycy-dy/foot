import copy
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from foot_web.services.versions import RULE_FILES

from conftest import FakeFetcher, login

NOW = datetime(2026, 11, 4, 12, tzinfo=ZoneInfo('Asia/Shanghai'))


def payload_for(match):
    from foot_web.services.research import option_catalog
    options = match.get('research_options') or option_catalog(match)
    return {
        'hypothesis': '未查到充分非赔率依据，仅按市场基准',
        'counterargument': '缺关键阵容核实',
        'failure_paths': ['核心未出场使实力假设失效', '比赛节奏与预期相反'],
        'quality_gaps': ['没有正式首发', '独立预测模型未运行'],
        'sources': [],
        'dimensions': [
            {'id': i, 'status': 'unknown', 'home': '待核', 'away': '待核',
             'impact': '仅作条件判断', 'source_ids': []} for i in range(1, 24)
        ],
        'assessments': [
            {'option_id': o['id'], 'decision': 'retain', 'reasons': [
                '未查到非赔率依据，仅按市场基准', '本项需要比赛沿对应结算路径发展'],
             'source_ids': [], 'risk': '阵容与路径未核实', 'withdraw_if': '出现已确认的反向阵容或路径证据',
             'mechanism': '对照本项的比分或分差条件，阵容未知使结论不稳定'}
            for o in options
        ],
        'scenarios': [{'name': '核心缺阵', 'condition': '官方确认核心缺阵',
                       'impact': '关键进攻组织待重新核查', 'action': '重新审查相关方向', 'source_ids': []}],
    }


@pytest.fixture
def project(cfg, tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    original = Path(cfg['PROJECT_DIR'])
    for name in RULE_FILES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes((original / name).read_bytes())
    return cfg | {'PROJECT_DIR': str(root), 'DATA_DIR': str(tmp_path / 'state')}


def test_evidence_contract_rejects_duplicates_future_sources_and_unknown_options():
    from foot_web.services.research import validate_evidence
    from foot_web.data.markets import parse_football
    match = parse_football(FakeFetcher().data['football'])[0]
    original = payload_for(match)
    assert validate_evidence(original, match, NOW)['dimensions'][0]['status'] == 'unknown'
    for change in ('duplicate', 'missing', 'source', 'future', 'bad_url', 'option', 'probability'):
        data = copy.deepcopy(original)
        if change == 'duplicate':
            data['dimensions'][1]['id'] = 1
        elif change == 'missing':
            data['dimensions'].pop()
        elif change == 'source':
            data['dimensions'][0]['status'] = 'verified'
        elif change in ('future', 'bad_url'):
            data['sources'] = [{'id': 'src', 'url': 'http://127.0.0.1/admin' if change == 'bad_url' else 'https://example.org/team-news',
                                'title': '来源', 'published_at': (NOW + timedelta(hours=1)).isoformat(),
                                'effective_at': NOW.isoformat(), 'group_id': 'original-news', 'tier': 'L1'}]
        elif change == 'option':
            data['assessments'][0]['option_id'] = 'invented'
        else:
            data['model_probability'] = .99
        with pytest.raises(ValueError):
            validate_evidence(data, match, NOW)


def test_partial_task_resume_does_not_repeat_completed_matches(project):
    from foot_web.engine.tasks import AnalysisTasks, run_task
    from foot_web.storage.research import ResearchStore
    tasks = AnalysisTasks(project, launcher=lambda *args: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')
    calls = []

    def generate(provider, prompt, workspace, config, **kwargs):
        match = json.loads(prompt.split('=== MATCH INPUT ===\n')[1])
        calls.append((match['sport'], match['num'], provider))
        if match['num'].endswith('003'):
            from foot_web.engine.providers import ProviderError
            raise ProviderError('execution_failed', '模拟一场上游失败')
        return payload_for(match)

    run_task(project, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=NOW)
    first = tasks.get(task['id'])
    assert first['status'] == 'partial'
    assert first['progress']['completed'] > 0 and first['progress']['failed'] > 0
    checkpoints = ResearchStore(project['DATA_DIR']).items(task['id'])
    completed = {(r['sport'], r['num']) for r in checkpoints if r['status'] == 'succeeded'}
    assert completed
    resumed, reused = tasks.resume(task['id'], 'admin1')
    assert resumed['id'] == task['id'] and not reused
    second_calls = []

    def recover(provider, prompt, workspace, config, **kwargs):
        if '=== RECOMMENDATION DECISION INPUT ===' in prompt:
            from conftest import decision_response
            return decision_response(prompt)
        match = json.loads(prompt.split('=== MATCH INPUT ===\n')[1])
        second_calls.append((match['sport'], match['num']))
        return payload_for(match)

    run_task(project, task['id'], fetcher=FakeFetcher(), generate=recover, as_of=NOW)
    assert tasks.get(task['id'])['status'] == 'succeeded'
    assert not (set(second_calls) & completed)
    folder = Path(project['PROJECT_DIR']) / 'runs' / '2026-11-04' / task['id']
    assert (folder / 'recommendations.draft.json').is_file()
    assert (folder / 'report.draft.md').is_file()
    assert not (folder / 'report.md').exists()


def test_cancel_is_persisted_and_resume_is_deduplicated(project):
    from foot_web.engine.tasks import AnalysisTasks, run_task
    tasks = AnalysisTasks(project, launcher=lambda *args: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')

    def generate(provider, prompt, workspace, config, **kwargs):
        tasks.cancel(task['id'], 'admin1')
        from foot_web.engine.providers import ProviderError
        raise ProviderError('cancelled', '已取消')

    run_task(project, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=NOW)
    assert tasks.get(task['id'])['status'] == 'cancelled'
    first, reused = tasks.resume(task['id'], 'admin1')
    second, reused2 = tasks.resume(task['id'], 'admin1')
    assert first['id'] == second['id'] and not reused and reused2


def test_control_routes_require_admin_csrf_and_render_checkpoints(client, app, identity):
    login(client, identity)
    tasks = app.extensions['analysis_tasks']
    task, _ = tasks.start('2026-11-04', 'admin1')
    for action in ('cancel', 'resume'):
        assert client.post(f'/api/analysis/{task["id"]}/{action}', json={}).status_code == 400
    with client.session_transaction() as session:
        headers = {'X-CSRF': session['csrf']}
    assert client.post(f'/api/analysis/{task["id"]}/cancel', json={}, headers=headers).status_code == 200
    assert '逐场进度' in client.get(task['result_url']).get_data(as_text=True)
    assert client.get(f'/api/analysis/{task["id"]}/matches').status_code == 200


def test_interrupted_composition_can_resume_without_model_calls(project, monkeypatch):
    from conftest import research_response
    from foot_web.engine import workflow
    from foot_web.engine.tasks import AnalysisTasks, run_task

    tasks = AnalysisTasks(project, launcher=lambda *args: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')
    original = workflow.write_once
    failed = False

    def fail_once(path, text):
        nonlocal failed
        if path.name == 'report.draft.md' and not failed:
            failed = True
            raise OSError('模拟报告保存中断')
        return original(path, text)

    monkeypatch.setattr(workflow, 'write_once', fail_once)
    run_task(project, task['id'], fetcher=FakeFetcher(),
             generate=lambda provider, prompt, *a, **kw: research_response(prompt), as_of=NOW)
    assert tasks.get(task['id'])['status'] == 'partial'
    folder = Path(project['PROJECT_DIR']) / 'runs' / '2026-11-04' / task['id']
    before = (folder / 'recommendations.draft.json').read_bytes()
    tasks.resume(task['id'], 'admin1')

    def forbidden(*args, **kwargs):
        raise AssertionError('已完成逐场证据不能重新调用模型')
    run_task(project, task['id'], fetcher=FakeFetcher(), generate=forbidden, as_of=NOW)
    assert tasks.get(task['id'])['status'] == 'succeeded'
    assert (folder / 'recommendations.draft.json').read_bytes() == before
    assert (folder / 'report.draft.md').is_file()


def test_no_price_or_probability_is_exposed_to_the_research_prompt():
    from foot_web.services.research import make_match_prompt
    from foot_web.data.markets import parse_basketball
    match = parse_basketball(FakeFetcher().data['basketball'])[0]
    prompt = make_match_prompt(match, '规则', NOW)
    identity = json.loads(prompt.split('=== MATCH INPUT ===\n')[1])
    assert not any(key in identity for key in ('mnl', 'hdc', 'hilo', 'had', 'options'))
    assert identity['research_options']
    for option in identity['research_options']:
        assert set(option) == {'id', 'market', 'label', 'line'}


@pytest.mark.parametrize('failure', ['invalid_output', 'unavailable', 'cleanup_failed', 'cancelled'])
def test_ai_decision_failure_preserves_research_and_resume_only_decides(project, failure):
    from conftest import research_response
    from foot_web.engine.providers import ProviderError
    from foot_web.engine.tasks import AnalysisTasks, run_task
    tasks = AnalysisTasks(project, launcher=lambda *args: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')
    decisions = []

    def generate(provider, prompt, *args, **kwargs):
        if '=== RECOMMENDATION DECISION INPUT ===' not in prompt:
            return research_response(prompt)
        decisions.append(provider)
        if failure == 'invalid_output':
            return {'not_a_decision': True}
        raise ProviderError(failure, '模拟推荐决策失败')

    run_task(project, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=NOW)
    assert tasks.get(task['id'])['status'] == ('cancelled' if failure == 'cancelled' else 'partial')
    assert tasks.get(task['id'])['progress']['completed'] == 28
    assert decisions == ['codex']
    folder = Path(project['PROJECT_DIR']) / 'runs' / '2026-11-04' / task['id']
    assert not (folder / 'recommendations.draft.json').exists()
    assert not (folder / 'ai-decision.json').exists()
    assert len(list(folder.glob('decision-*/attempts.json'))) == 1
    tasks.resume(task['id'], 'admin1')

    def recover(provider, prompt, *args, **kwargs):
        assert '=== RECOMMENDATION DECISION INPUT ===' in prompt, '已完成逐场证据不应重跑'
        return research_response(prompt)

    run_task(project, task['id'], fetcher=FakeFetcher(), generate=recover, as_of=NOW)
    assert tasks.get(task['id'])['status'] == 'succeeded'
    assert len(list(folder.glob('decision-*/attempts.json'))) == 2
    assert (folder / 'ai-decision.json').exists()


def test_ai_decision_invalid_codex_does_not_fallback(project):
    from conftest import research_response
    from foot_web.engine.tasks import AnalysisTasks, run_task
    tasks = AnalysisTasks(project, launcher=lambda *args: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')

    def generate(provider, prompt, *args, **kwargs):
        if '=== RECOMMENDATION DECISION INPUT ===' in prompt and provider == 'codex':
            return {'not_a_decision': True}
        return research_response(prompt)

    run_task(project, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=NOW)
    assert tasks.get(task['id'])['status'] == 'partial'
    folder = Path(project['PROJECT_DIR']) / 'runs' / '2026-11-04' / task['id']
    assert not (folder / 'ai-decision.json').exists()
    assert not (folder / 'recommendations.draft.json').exists()
    assert not (folder / 'report.md').exists()
    attempts_paths = list(folder.glob('decision-*/attempts.json'))
    assert len(attempts_paths) == 1
    assert json.loads(attempts_paths[0].read_text()) == [
        {'provider': 'codex', 'status': 'failed', 'code': 'invalid_output'}]
    assert json.loads((attempts_paths[0].parent / 'codex.response.json').read_text()) == {'not_a_decision': True}
    assert not (attempts_paths[0].parent / 'validated.json').exists()


def test_workflow_attempt_messages_are_redacted(project):
    from foot_web.engine.providers import ProviderError
    from foot_web.engine.tasks import AnalysisTasks, run_task
    tasks = AnalysisTasks(project, launcher=lambda *args: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')

    def fail(*args, **kwargs):
        raise ProviderError('unavailable', 'api_key=private-value-not-for-storage')
    run_task(project, task['id'], fetcher=FakeFetcher(), generate=fail, as_of=NOW)
    assert 'private-value-not-for-storage' not in json.dumps(tasks.get(task['id']))
    assert 'private-value-not-for-storage' not in json.dumps(tasks.research.items(task['id']))


def test_new_quote_round_can_reuse_recent_same_day_evidence_but_requires_new_ai_decision(project):
    from conftest import research_response
    from foot_web.engine.tasks import AnalysisTasks, run_task
    tasks = AnalysisTasks(project, launcher=lambda *args: os.getpid())
    first, _ = tasks.start('2026-11-04', 'admin1')
    generator = lambda provider, prompt, *a, **kw: research_response(prompt)
    run_task(project, first['id'], fetcher=FakeFetcher(), generate=generator, as_of=NOW)
    assert tasks.get(first['id'])['status'] == 'succeeded'
    second, _ = tasks.start('2026-11-04', 'admin1', reuse_from=first['id'])
    calls = []
    def cached_round(provider, prompt, *a, **kw):
        calls.append(prompt)
        assert '=== RECOMMENDATION DECISION INPUT ===' in prompt, '有效证据不应重新调用逐场CLI'
        return research_response(prompt)
    run_task(project, second['id'], fetcher=FakeFetcher(), generate=cached_round, as_of=NOW+timedelta(minutes=10))
    completed = tasks.get(second['id'])
    assert completed['status'] == 'succeeded'
    assert completed['progress']['reused'] == tasks.get(first['id'])['progress']['completed']
    assert len(calls) == 1
    assert all(row['as_of'] == NOW.isoformat() for row in tasks.research.items(second['id']) if row['status'] == 'succeeded')


def test_future_applicability_is_allowed_only_if_already_published_for_this_match():
    from conftest import research_payload
    from foot_web.data.markets import parse_football
    from foot_web.services.research import validate_evidence
    match = parse_football(FakeFetcher().data['football'])[0]
    payload = research_payload(match)
    payload['sources'] = [{'id': 'lineup', 'url': 'https://example.org/fixture-lineup', 'title': '测试名单',
                          'published_at': (NOW-timedelta(minutes=5)).isoformat(),
                          'effective_at': match['kickoff'], 'group_id': 'official-fixture', 'tier': 'L1'}]
    payload['dimensions'][17].update(status='verified', source_ids=['lineup'])
    assert validate_evidence(payload, match, NOW)
    payload['sources'][0]['published_at'] = (NOW+timedelta(minutes=5)).isoformat()
    with pytest.raises(ValueError):
        validate_evidence(payload, match, NOW)


def test_unverified_source_cannot_be_used_as_a_factual_veto():
    from conftest import research_payload
    from foot_web.data.markets import parse_football
    from foot_web.services.research import validate_evidence
    match = parse_football(FakeFetcher().data['football'])[0]
    payload = research_payload(match)
    payload['sources'] = [{'id': 'rumour', 'url': 'https://example.org/fixture-news', 'title': '测试线索',
                          'published_at': NOW.isoformat(), 'effective_at': NOW.isoformat(),
                          'group_id': 'rumour', 'tier': 'L3'}]
    payload['assessments'][0].update(decision='veto', source_ids=['rumour'])
    with pytest.raises(ValueError):
        validate_evidence(payload, match, NOW)
    payload['sources'][0]['tier'] = 'L1'
    payload['dimensions'][3].update(status='verified', source_ids=['rumour'])
    assert validate_evidence(payload, match, NOW)
