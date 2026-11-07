"""Issue #9: isolated fake-generator tests; never invokes a real CLI."""
import json
import os
from pathlib import Path

import pytest

from conftest import FakeFetcher, decision_response
from test_research_workflow import NOW, payload_for, project  # noqa: F401
from foot_web.engine.providers import ProviderError
from foot_web.engine.tasks import AnalysisTasks, prepare_input
from foot_web.engine import workflow


@pytest.fixture
def run_round(project):
    tasks = AnalysisTasks(project, launcher=lambda *args: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')

    def prepare(*args):
        source = prepare_input(*args)
        source['football'] = source['football'][:2]
        source['basketball'] = []
        return source

    def run(generator):
        def dispatch(provider, prompt, *args, **kwargs):
            if '=== RECOMMENDATION DECISION INPUT ===' in prompt:
                return decision_response(prompt)
            return generator(provider, prompt, *args, **kwargs)
        workflow.run_workflow(project, task['id'], prepare, dispatch,
                              fetcher=FakeFetcher(), as_of=NOW)
        folder = Path(project['PROJECT_DIR']) / 'runs' / '2026-11-04' / task['id']
        return tasks.get(task['id']), tasks.research.items(task['id']), folder
    return run, tasks, task


def original_match(prompt):
    return json.loads(prompt.split('=== MATCH INPUT ===\n')[1])


def invalid_evidence(match):
    result = payload_for(match)
    result['sources'] = [{'id': 'real', 'url': 'https://example.org/news', 'title': '真实来源',
                          'published_at': None, 'effective_at': None, 'tier': 'L2', 'group_id': 'real'}]
    result['dimensions'][0]['status'] = 'verified'
    return result


def test_repair_same_provider_preserves_raw_failures_and_real_sources(run_round):
    run, _, _ = run_round
    calls = []

    def generate(provider, prompt, workspace, config, **kwargs):
        calls.append((provider, prompt, int(config['FOOT_ANALYSIS_TIMEOUT'])))
        match = original_match(prompt)
        value = invalid_evidence(match)
        if '=== VALIDATION FAILURE ===' in prompt:
            assert 'unknown' in prompt and '不编造新数据' in prompt and '保留真实source' in prompt
            value['dimensions'][0]['status'] = 'unknown'
        return value

    task, items, folder = run(generate)
    assert task['status'] == 'succeeded'
    assert [c[0] for c in calls] == ['claude'] * 4
    for item in items:
        assert [a['stage'] for a in item['attempts']] == ['research', 'evidence_repair']
        assert [a['status'] for a in item['attempts']] == ['failed', 'succeeded']
        assert item['payload']['sources'][0]['id'] == 'real'
        assert item['payload']['dimensions'][0]['status'] == 'unknown'
        checkpoint = folder / 'matches' / item['match_key']
        raw = [json.loads((checkpoint / a['response']).read_text()) for a in item['attempts']]
        assert raw[0]['dimensions'][0]['status'] == 'verified'
        assert raw[1]['dimensions'][0]['status'] == 'unknown'
        for attempt in item['attempts']:
            assert json.loads((checkpoint / attempt['attempt_artifact']).read_text()) == attempt
    assert all(calls[i + 1][2] <= calls[i][2] for i in (0, 2))


def test_only_one_repair_then_codex_fallback_without_python_mutation(run_round):
    run, _, _ = run_round
    calls = []

    def generate(provider, prompt, *args, **kwargs):
        calls.append(provider)
        match = original_match(prompt)
        result = invalid_evidence(match) if provider == 'claude' else payload_for(match)
        return result

    task, items, folder = run(generate)
    assert task['status'] == 'succeeded'
    assert calls == ['claude', 'claude', 'codex'] * 2
    assert all(i['payload']['sources'] == [] for i in items)
    for i in items:
        assert [a['code'] for a in i['attempts']] == ['invalid_output', 'invalid_output', 'ok']
        checkpoint = folder / 'matches' / i['match_key']
        assert json.loads((checkpoint / i['attempts'][0]['response']).read_text())['dimensions'][0]['status'] == 'verified'


def test_both_providers_invalid_stop_after_one_repair_each(run_round):
    run, _, _ = run_round
    calls = []

    def generate(provider, prompt, *args, **kwargs):
        calls.append(provider)
        return invalid_evidence(original_match(prompt))

    task, items, _ = run(generate)
    assert task['status'] == 'failed'
    assert calls == ['claude', 'claude', 'codex', 'codex'] * 2
    assert all(i['payload'] is None for i in items)
    assert all(len(i['attempts']) == 4 for i in items)


@pytest.mark.parametrize('code', ['timeout', 'authentication', 'configuration', 'invalid_output'])
def test_generator_error_never_triggers_repair_and_config_skips_round(run_round, code):
    run, _, _ = run_round
    calls = []

    def generate(provider, prompt, *args, **kwargs):
        assert '=== VALIDATION FAILURE ===' not in prompt
        calls.append(provider)
        if provider == 'claude':
            raise ProviderError(code, '原调用失败')
        return payload_for(original_match(prompt))

    task, items, _ = run(generate)
    assert task['status'] == 'succeeded'
    assert calls == (['claude', 'codex', 'codex'] if code in ('authentication', 'configuration')
                     else ['claude', 'codex', 'claude', 'codex'])
    assert not any(a['stage'] == 'evidence_repair' for i in items for a in i['attempts'])


@pytest.mark.parametrize('code', ['cancelled', 'cleanup_failed'])
@pytest.mark.parametrize('during_repair', [False, True])
def test_cleanup_and_cancel_stop_immediately(run_round, code, during_repair):
    run, _, _ = run_round
    calls = []

    def generate(provider, prompt, *args, **kwargs):
        calls.append(provider)
        if during_repair and len(calls) == 1:
            return invalid_evidence(original_match(prompt))
        raise ProviderError(code, '立即停止')

    task, items, _ = run(generate)
    assert calls == ['claude'] * (2 if during_repair else 1)
    assert task['status'] == ('cancelled' if code == 'cancelled' else 'failed')
    assert items[0]['attempts'][-1]['code'] == code


def test_preserved_returns_and_validation_messages_are_redacted(run_round):
    run, _, _ = run_round

    def generate(provider, prompt, *args, **kwargs):
        value = payload_for(original_match(prompt))
        value['api_key=private-return-secret'] = 'api_key=private-value-secret'
        if '=== VALIDATION FAILURE ===' in prompt:
            assert 'private-return-secret' not in prompt
            assert 'private-value-secret' not in prompt
            return payload_for(original_match(prompt))
        return value

    task, _, folder = run(generate)
    assert task['status'] == 'succeeded'
    assert 'private-value-secret' not in json.dumps(task)
    for path in folder.glob('matches/*/*.json'):
        assert 'private-value-secret' not in path.read_text()


def test_cancel_after_return_never_repairs(run_round):
    run, tasks, task = run_round
    calls = []

    def generate(provider, prompt, *args, **kwargs):
        calls.append(provider)
        tasks.cancel(task['id'], 'admin1')
        return invalid_evidence(original_match(prompt))

    result, items, folder = run(generate)
    assert calls == ['claude']
    assert result['status'] == 'cancelled'
    assert items[0]['attempts'][0]['code'] == 'cancelled'
    assert (folder / 'matches' / items[0]['match_key'] / items[0]['attempts'][0]['response']).exists()


@pytest.mark.parametrize('limit', ['match', 'total'])
def test_repair_uses_only_remaining_original_budget(run_round, monkeypatch, limit):
    run, tasks, _ = run_round
    tasks.config['FOOT_MATCH_TIMEOUT'] = '60'
    tasks.config['FOOT_ANALYSIS_BUDGET'] = '60' if limit == 'total' else '600'
    elapsed = [0.0]
    monkeypatch.setattr(workflow.time, 'monotonic', lambda: elapsed[0])
    calls = []

    def generate(provider, prompt, workspace, config, **kwargs):
        calls.append((provider, int(config['FOOT_ANALYSIS_TIMEOUT']), '=== VALIDATION FAILURE ===' in prompt))
        match = original_match(prompt)
        if not calls[-1][2]:
            elapsed[0] += 25
            return invalid_evidence(match)
        return payload_for(match)

    _, _, _ = run(generate)
    assert calls[:2] == [('claude', 60, False), ('claude', 35, True)]


def test_insufficient_remaining_budget_skips_repair(run_round, monkeypatch):
    run, tasks, _ = run_round
    tasks.config['FOOT_MATCH_TIMEOUT'] = '30'
    tasks.config['FOOT_ANALYSIS_BUDGET'] = '30'
    elapsed = [0.0]
    monkeypatch.setattr(workflow.time, 'monotonic', lambda: elapsed[0])
    calls = []

    def generate(provider, prompt, *args, **kwargs):
        calls.append(provider)
        elapsed[0] = 25
        return invalid_evidence(original_match(prompt))

    task, items, _ = run(generate)
    assert calls == ['claude']
    assert task['status'] == 'failed'
    assert [a['code'] for a in items[0]['attempts']] == ['invalid_output', 'timeout']
