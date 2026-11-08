"""Offline AI-return gates; never launch real CLIs or consume account quota."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from foot_web.engine.decisions import decide
from foot_web.engine.providers import ProviderError
from foot_web.engine.review_tasks import run_review
from foot_web.services.reviews import ReviewService
from foot_web.services.review_analysis import validate_review
from foot_web.storage.jobs import JobsStore


def response(rows):
    return {'summary': 'AI返回的复盘总结：仅按市场基准，不能证明原逻辑正确。',
            'tickets': [{'ticket_id': r['ticket_id'], 'assessment': 'AI评估：原选项命中，不能反推预测可靠。',
                         'failure_paths': '可能失败路径待证实。', 'evidence_gaps': '缺少赛前非赔率证据，归因证据不足。',
                         'improvements': '下一次保存带时点的实力证据。'} for r in rows],
            'limitations': '仅解释给定冻结资料，不修改原票与结算。'}


def test_decision_failure_does_not_fallback(tmp_path):
    calls = []
    def generator(provider, prompt, folder, config, **kwargs):
        calls.append(provider)
        if provider == 'codex':
            return {'answer': ''}
        return {'answer': 'Codex的离线模拟返回'}
    def validate(value):
        if not value.get('answer'):
            raise ValueError('empty')
        return value
    folder = tmp_path / 'decision'
    with pytest.raises(ProviderError) as error:
        decide({}, folder, 'input', {}, validate, generator=generator)
    assert error.value.code == 'ai_unavailable'
    assert calls == ['codex']
    assert json.loads((folder / 'codex.response.json').read_text()) == {'answer': ''}
    assert not (folder / 'validated.json').exists()
    assert json.loads((folder / 'attempts.json').read_text()) == [
        {'provider': 'codex', 'status': 'failed', 'code': 'invalid_output'}]
    with pytest.raises(FileExistsError):
        decide({}, folder, 'other', {}, validate, generator=generator)


def test_valid_codex_decision_persists_actual_return_hashes(tmp_path):
    calls = []
    def generator(provider, *args, **kwargs):
        calls.append(provider)
        assert args[2]['_tools_disabled'] is True
        return {'answer': 'Codex的离线模拟返回'}
    folder = tmp_path / 'valid-decision'
    result = decide({}, folder, 'input', {}, lambda value: value, generator=generator)
    assert calls == ['codex'] and result['provider'] == 'codex'
    assert result['result']['answer'] == 'Codex的离线模拟返回'
    for field, filename in [('response_sha256', 'codex.response.json'),
                            ('schema_sha256', 'schema.json'), ('validated_sha256', 'validated.json')]:
        assert result[field] == hashlib.sha256((folder / filename).read_bytes()).hexdigest()
    assert result['attempts'] == [{'provider': 'codex', 'status': 'succeeded', 'code': 'ok'}]


@pytest.mark.parametrize('code,expected', [('timeout', ['codex']), ('cleanup_failed', ['codex']), ('cancelled', ['codex'])])
def test_decision_failure_never_synthetic_success(tmp_path, code, expected):
    calls = []
    def generator(provider, *args, **kwargs):
        calls.append(provider)
        raise ProviderError(code, 'failure')
    with pytest.raises(ProviderError):
        decide({}, tmp_path / 'failed', 'input', {}, lambda x: x, generator=generator)
    assert calls == expected
    assert not (tmp_path / 'failed' / 'validated.json').exists()


def test_decision_never_truncates_evidence_or_return(tmp_path):
    prompt = 'x' * 12000 + 'FULL_EVIDENCE_END'
    answer = 'y' * 8000 + 'FULL_RETURN_END'
    def generator(provider, sent, folder, config, **kwargs):
        assert sent == prompt
        return {'answer': answer}
    result = decide({}, tmp_path / 'long', prompt, {}, lambda x: x, generator=generator)
    assert result['result']['answer'] == answer
    assert (tmp_path / 'long/prompt.txt').read_text() == prompt
    assert result['model'] is None  # Native CLI defaults are not a verified model identity.


def test_oversized_input_fails_without_truncating_or_calling_provider(tmp_path):
    calls = []
    with pytest.raises(ProviderError) as error:
        decide({}, tmp_path / 'oversized', 'x' * 2_000_001, {}, lambda x: x,
               generator=lambda *a, **kw: calls.append(a))
    assert error.value.code == 'invalid_input'
    assert calls == [] and not (tmp_path / 'oversized/validated.json').exists()


def test_redaction_handles_long_keys_without_losing_sensitive_assignments():
    from foot_web.engine.logs import redact
    text = 'x' * 120_000 + ' token' * 20_000
    assert redact(text, limit=None) == text
    for key in ('token', 'prefix_api_key_suffix', 'a.token.suffix', 'CLIENT_SECRET', 'password', 'authorization'):
        value = json.dumps({key: 'private-value', 'note': 'token=inner-secret'})
        redacted = redact(value, limit=None)
        assert 'private-value' not in redacted and 'inner-secret' not in redacted
    assert redact('"note": "innocent-value"', limit=None) == '"note": "innocent-value"'


def test_redaction_preserves_json_and_frozen_policy_nulls():
    from foot_web.core.privacy import redact
    policy = 'actual_stake_and_return_without_user_authorization: null\nledger: frozen\napi_key=private-value'
    safe = redact(policy, limit=None)
    assert 'authorization: null\nledger: frozen' in safe and 'private-value' not in safe
    serialized = json.dumps({'rules': safe, 'token': 'private-token'})
    returned = json.loads(redact(serialized, limit=None))
    assert returned == {'rules': safe, 'token': '[REDACTED]'}
    assert redact(redact(serialized, limit=None), limit=None) == redact(serialized, limit=None)


def test_decision_redacts_input_return_and_events(tmp_path):
    events = []
    secret = 'sensitive-value-for-test'
    def generator(provider, prompt, folder, config, **kwargs):
        assert secret not in prompt
        kwargs['on_event']('status', secret)
        return {'answer': secret}
    result = decide({'DINGTALK_CLIENT_SECRET': secret}, tmp_path / 'safe', 'input ' + secret, {}, lambda x: x,
                    generator=generator, on_event=lambda *args: events.append(args))
    assert secret not in json.dumps(result) and secret not in json.dumps(events)
    assert all(secret not in p.read_text() for p in (tmp_path / 'safe').iterdir() if p.is_file())


@pytest.fixture
def review_case(tmp_path):
    cfg = {'PROJECT_DIR': str(tmp_path), 'DATA_DIR': str(tmp_path / 'var')}
    from conftest import copy_rules
    copy_rules(tmp_path)
    ticket = {'business_date': '2026-11-04', 'ledger': 'rec', 'kind': '足球最终串',
              'title': '原票', 'source_file': 'original.md', 'snapshot': '2026-11-04T12:00:00+08:00',
              'legs': [{'sport': 'football', 'number': '周三001', 'matchup': '主队 VS 客队', 'market': 'HAD',
                        'goal_line': '', 'options': [{'key': 'h', 'label': '主胜', 'odds': '1.80'}]}]}
    folder = tmp_path / 'ledger/data'
    folder.mkdir(parents=True)
    (folder / 'records_test.jsonl').write_text(json.dumps(ticket) + '\n')
    results = {'football': [{'matchNumStr': '周三001', 'matchDate': '2026-11-04',
                            'allHomeTeam': '主队', 'allAwayTeam': '客队', 'matchResultStatus': '2',
                            'sectionsNo999': '2:1', 'sectionsNo1': '1:0'}], 'sources': []}
    return cfg, results


def test_production_review_requires_ai_return_before_overlay(review_case, monkeypatch):
    from foot_web.data.results import ResultsFetcher
    from foot_web.engine import decisions
    cfg, results = review_case
    monkeypatch.setattr(ResultsFetcher, 'fetch', lambda *a, **kw: copy.deepcopy(results))
    calls = []
    def generator(provider, prompt, folder, config, **kwargs):
        calls.append(provider)
        assert provider == 'codex'
        data = json.loads(prompt.split('=== FROZEN REVIEW DATA ===\n')[1])
        return response(data['rows'])
    monkeypatch.setattr(decisions, 'generate', generator)
    jobs = JobsStore(cfg['DATA_DIR'])
    jobs.begin_review('ai-review-one', '2026-11-04', 'admin1')
    run_review(cfg, 'ai-review-one')
    assert jobs.review('ai-review-one')['status'] == 'succeeded'
    assert calls == ['codex']
    folder = Path(cfg['PROJECT_DIR']) / 'runs/2026-11-04/ai-review-one'
    result = json.loads((folder / 'settlement.json').read_text())
    assert result['analysis_mode'] == 'ai_review'
    assert result['ai_analysis']['provider'] == 'codex'
    assert result['rows'][0]['hit'] is True and result['rows'][0]['theoretical_return'] == '3.60'
    assert result['rows'][0]['actual_return'] is None
    report = (folder / 'review.md').read_text()
    assert 'AI返回的复盘总结' in report and 'AI逐票解释' in report and 'codex' in report
    manifest = json.loads((folder / 'manifest.json').read_text())
    assert manifest['ai_analysis']['response_sha256']
    assert manifest['ai_analysis']['provider'] == result['ai_analysis']['provider'] == 'codex'
    # Later Codex failure must not replace the last real AI success.
    monkeypatch.setattr(decisions, 'generate', lambda *a, **kw: (_ for _ in ()).throw(ProviderError('timeout', 'timeout')))
    jobs.begin_review('ai-review-failed', '2026-11-04', 'admin1')
    run_review(cfg, 'ai-review-failed')
    assert jobs.review('ai-review-failed')['status'] == 'failed'
    assert 'AI复盘未完成' in jobs.review('ai-review-failed')['message']
    with jobs.store.connect() as db:
        assert db.execute('SELECT run_id FROM review_current').fetchone()['run_id'] == 'ai-review-one'
    failed_folder = folder.parent / 'ai-review-failed'
    assert not (failed_folder / 'review.md').exists()
    assert json.loads((failed_folder / 'tickets.json').read_text())
    assert json.loads((failed_folder / 'results.json').read_text()) == results


def test_review_validation_covers_identity_and_disallows_settlement_rewrite():
    rows = [{'ticket_id': 'one'}, {'ticket_id': 'two'}]
    payload = response(rows)
    assert validate_review(payload, rows) is payload
    for mutate in ('missing', 'duplicate', 'unknown', 'rewrite'):
        value = copy.deepcopy(payload)
        if mutate == 'missing':
            value['tickets'].pop()
        elif mutate == 'duplicate':
            value['tickets'][1]['ticket_id'] = 'one'
        elif mutate == 'unknown':
            value['tickets'][1]['ticket_id'] = 'fake'
        else:
            value['tickets'][0]['hit'] = True
        with pytest.raises(ValueError):
            validate_review(value, rows)


def test_historical_review_ui_not_relabelled_ai(client, identity, app, tmp_path):
    from conftest import login
    login(client, identity)
    config = app.config['FOOT']
    app.config['FOOT'] = config | {'PROJECT_DIR': str(tmp_path)}
    jobs = app.extensions['jobs']
    jobs.begin_review('legacy-review', '2026-11-04', 'admin1')
    jobs.update_review('legacy-review', status='succeeded')
    folder = tmp_path / 'runs/2026-11-04/legacy-review'
    folder.mkdir(parents=True)
    (folder / 'review.md').write_text('# 历史确定性结算\n\n没有AI结果。')
    html = client.get('/reviews/legacy-review').get_data(as_text=True)
    assert '历史/纯结算版本' in html and '未保存AI分析，不追溯标记' in html
    (folder / 'manifest.json').write_text(json.dumps({'analysis_mode': 'ai_review'}))
    html = client.get('/reviews/legacy-review').get_data(as_text=True)
    assert 'DeepSeek Harness AI分析' in html and '历史/纯结算版本' not in html


def test_settlement_only_cannot_masquerade_as_ai(review_case):
    cfg, results = review_case
    class Fetcher:
        def fetch(self, *a, **kw):
            return results
    result = ReviewService(cfg, fetcher=Fetcher()).run('2026-11-04', 'pure-calculation')
    assert result['analysis_mode'] == 'settlement_only' and 'ai_analysis' not in result
    assert '纯结算（非AI复盘）' in (Path(result['folder']) / 'review.md').read_text()
