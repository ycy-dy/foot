"""Offline routing/provenance checks: no real CLI, credentials or production DB."""
import copy
import json
import os
from pathlib import Path

import pytest

from foot_web.engine.decisions import decide
from foot_web.engine.providers import ProviderError
from foot_web.services.research import fingerprint
from foot_web.services.selection import DECISION_SCHEMA, load_decision, make_decision_prompt
from foot_web.services.versions import rules_manifest, same_version


@pytest.fixture
def harness_policy(tmp_path):
    from conftest import copy_rules, set_policy_provider
    copy_rules(tmp_path)
    set_policy_provider(tmp_path, 'harness')
    return {'PROJECT_DIR': str(tmp_path)}


def test_harness_decision_preserves_full_input_and_artifacts(tmp_path, harness_policy):
    prompt = '研究资料' * 100_000 + 'FULL_INPUT_END'
    answer = {'answer': '证据' * 8000 + 'FULL_RETURN_END'}
    calls = []

    def generate(provider, sent, folder, config, **kwargs):
        calls.append(provider)
        assert sent == prompt
        return answer

    result = decide(harness_policy, tmp_path / 'decision-new', prompt, {}, lambda value: value, generator=generate)
    assert calls == ['harness'] and result['provider'] == 'harness'
    assert result['result'] == answer and result['model'] is None
    assert (tmp_path / 'decision-new/prompt.txt').read_text() == prompt
    assert json.loads((tmp_path / 'decision-new/harness.response.json').read_text()) == answer
    assert not list(tmp_path.rglob('claude.response.json'))
    assert not list(tmp_path.rglob('codex.response.json'))


@pytest.mark.parametrize('code', ['timeout', 'unavailable', 'authentication', 'rate_limit',
                                  'configuration', 'cleanup_failed', 'cancelled', 'invalid_output'])
def test_harness_failure_never_falls_back_to_legacy_cli(tmp_path, harness_policy, code):
    calls = []

    def generate(provider, *args, **kwargs):
        calls.append(provider)
        raise ProviderError(code, 'offline failure')

    folder = tmp_path / 'decision-failed'
    with pytest.raises(ProviderError):
        decide(harness_policy, folder, 'input', {}, lambda value: value, generator=generate)
    assert calls == ['harness']
    assert not (folder / 'validated.json').exists()
    assert json.loads((folder / 'attempts.json').read_text()) == [
        {'provider': 'harness', 'status': 'failed', 'code': code}]


def test_harness_invalid_return_cannot_claim_success(tmp_path, harness_policy):
    calls = []

    def generate(provider, *args, **kwargs):
        calls.append(provider)
        return {'not': 'valid'}

    def invalid(value):
        raise ValueError('bad evidence')

    folder = tmp_path / 'decision-invalid'
    with pytest.raises(ProviderError, match='harness'):
        decide(harness_policy, folder, 'input', {}, invalid, generator=generate)
    assert calls == ['harness']
    assert (folder / 'harness.response.json').exists()
    assert not (folder / 'validated.json').exists()


@pytest.fixture
def harness_artifacts(tmp_path, harness_policy):
    # Minimal context exercises immutable artifact identity without changing arithmetic.
    manifest, _ = rules_manifest(tmp_path)
    context = {'business_date': '2026-11-04', 'options': {}, 'slots': {}, 'evidence': [],
               'manifest': manifest}
    value = {'context_sha256': fingerprint(context), 'summary': '离线模拟决策',
             'vetoes': [], 'choices': [], 'assessments': []}
    envelope = decide(harness_policy, tmp_path / 'decision-offline', make_decision_prompt(context),
                      DECISION_SCHEMA, lambda raw: raw, generator=lambda *a, **kw: value)
    (tmp_path / 'ai-decision.json').write_text(json.dumps(envelope))
    (tmp_path / 'decision-context.json').write_text(json.dumps(context))
    return tmp_path, envelope, context


def test_load_harness_artifacts_accepts_unverified_model_none(harness_artifacts):
    folder, envelope, context = harness_artifacts
    assert envelope['model'] is None
    assert load_decision(folder) == (envelope, context)


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_load_decision_rejects_other_provider_even_with_matching_artifacts(harness_artifacts, provider):
    folder, envelope, _ = harness_artifacts
    envelope['provider'] = provider
    envelope['attempts'][-1]['provider'] = provider
    artifact = folder / envelope['artifact_dir']
    (artifact / (provider + '.response.json')).write_bytes((artifact / 'harness.response.json').read_bytes())
    (artifact / 'attempts.json').write_text(json.dumps(envelope['attempts']))
    (folder / 'ai-decision.json').write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match='历史参考'):
        load_decision(folder)


def test_cli_attempt_cannot_masquerade_as_harness_success(harness_artifacts):
    folder, envelope, _ = harness_artifacts
    envelope['attempts'].insert(0, {'provider': 'claude', 'status': 'failed', 'code': 'timeout'})
    (folder / envelope['artifact_dir'] / 'attempts.json').write_text(json.dumps(envelope['attempts']))
    (folder / 'ai-decision.json').write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match='真实成功'):
        load_decision(folder)


def test_harness_response_tampering_is_rejected(harness_artifacts):
    folder, envelope, _ = harness_artifacts
    (folder / envelope['artifact_dir'] / 'harness.response.json').write_text('{}')
    with pytest.raises(ValueError, match='哈希'):
        load_decision(folder)


def test_harness_config_env_precedence_without_reading_credentials(tmp_path, monkeypatch):
    from foot_web.core.config import load_config
    env = tmp_path / 'offline.env'
    env.write_text('FOOT_HARNESS_BIN=/offline/from-file\nFOOT_CLAUDE_BIN=/legacy/claude\n')
    monkeypatch.setenv('FOOT_HARNESS_BIN', '/offline/from-env')
    result = load_config(env)
    assert result['FOOT_HARNESS_BIN'] == '/offline/from-env'
    assert result['FOOT_CLAUDE_BIN'] == '/legacy/claude'  # configuration compatibility only


def test_runtime_version_rejects_legacy_or_changed_code(cfg):
    current, _ = rules_manifest(cfg['PROJECT_DIR'])
    assert current['runtime_provider'] == 'codex'
    assert not same_version(current, current | {'runtime_provider': 'harness'})
    assert same_version(current, copy.deepcopy(current))
    for key in ('runtime_provider', 'code_sha256', 'workflow_version', 'rules_sha256'):
        previous = current | {key: 'legacy-value'}
        assert not same_version(current, previous)
    legacy = {key: value for key, value in current.items() if key != 'runtime_provider'}
    assert not same_version(current, legacy)
    assert not same_version(legacy, legacy)


@pytest.fixture
def offline_project(cfg, tmp_path):
    from conftest import copy_rules, set_policy_provider
    root = tmp_path / 'project'
    copy_rules(root)
    set_policy_provider(root, 'harness')
    return cfg | {'PROJECT_DIR': str(root), 'DATA_DIR': str(tmp_path / 'offline-state')}


def test_analysis_research_and_final_decision_use_only_harness(offline_project):
    from conftest import ANALYSIS_ASOF, FakeFetcher, research_response
    from foot_web.engine.tasks import AnalysisTasks, run_task
    tasks = AnalysisTasks(offline_project, launcher=lambda *a: os.getpid())
    task, _ = tasks.start('2026-11-04', 'offline-admin')
    calls = []

    def generate(provider, prompt, *args, **kwargs):
        calls.append((provider, '=== RECOMMENDATION DECISION INPUT ===' in prompt))
        return research_response(prompt)

    run_task(offline_project, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=ANALYSIS_ASOF)
    assert tasks.get(task['id'])['status'] == 'succeeded'
    assert calls and {provider for provider, _ in calls} == {'harness'}
    assert any(final for _, final in calls) and any(not final for _, final in calls)
    folder = Path(offline_project['PROJECT_DIR']) / 'runs/2026-11-04' / task['id']
    envelope, _ = load_decision(folder)
    assert envelope['provider'] == 'harness'
    assert not (folder / 'report.md').exists()  # no automatic publication


def test_harness_unavailable_stops_research_without_cli_fallback(offline_project):
    from conftest import ANALYSIS_ASOF, FakeFetcher
    from foot_web.engine.tasks import AnalysisTasks, run_task
    tasks = AnalysisTasks(offline_project, launcher=lambda *a: os.getpid())
    task, _ = tasks.start('2026-11-04', 'offline-admin')
    calls = []

    def generate(provider, *args, **kwargs):
        calls.append(provider)
        raise ProviderError('unavailable', 'offline harness missing')

    run_task(offline_project, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=ANALYSIS_ASOF)
    assert calls == ['harness']
    assert tasks.get(task['id'])['status'] == 'failed'
    folder = Path(offline_project['PROJECT_DIR']) / 'runs/2026-11-04' / task['id']
    assert not (folder / 'ai-decision.json').exists()
    assert not (folder / 'recommendations.draft.json').exists()
