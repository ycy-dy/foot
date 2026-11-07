"""Offline policy/provider isolation; never runs a CLI or touches a production DB."""
import copy
import json
from pathlib import Path

import pytest
import yaml

from foot_web.core.config import load_config, runtime_provider
from foot_web.engine.decisions import decide
from foot_web.engine.providers import ProviderError
from foot_web.services.research import fingerprint
from foot_web.services.selection import DECISION_SCHEMA, load_decision, make_decision_prompt
from foot_web.services.versions import POLICY_BASE, active_provider, rules_manifest, same_version


def project(tmp_path, provider='codex'):
    from conftest import copy_rules
    root = tmp_path / provider
    copy_rules(root)
    path = root / (POLICY_BASE + '.yaml')
    policy = yaml.safe_load(path.read_text())
    policy['runtime_provider'] = provider
    policy['decision']['runtime_provider'] = provider
    policy['decision']['providers'] = [provider]
    path.write_text(yaml.safe_dump(policy, allow_unicode=True))
    return {'PROJECT_DIR': str(root), 'FOOT_AI_PROVIDER': provider}


@pytest.mark.parametrize('provider', ['codex', 'harness'])
def test_policy_is_single_source_and_manifest_matches(tmp_path, provider):
    config = project(tmp_path, provider)
    assert active_provider(config['PROJECT_DIR']) == runtime_provider(config) == provider
    manifest, _ = rules_manifest(config['PROJECT_DIR'])
    assert manifest['runtime_provider'] == provider
    assert manifest['compatibility'] == 'supported_subset'
    assert same_version(manifest, copy.deepcopy(manifest))
    assert not same_version(manifest, manifest | {'runtime_provider': 'claude'})
    assert not same_version(manifest, manifest | {'runtime_provider': 'harness' if provider == 'codex' else 'codex'})
    assert not same_version({}, {})
    with pytest.raises(ValueError, match='不一致'):
        runtime_provider(config | {'FOOT_AI_PROVIDER': 'harness' if provider == 'codex' else 'codex'})


def test_configuration_defaults_codex_and_rejects_claude(tmp_path, monkeypatch):
    monkeypatch.delenv('FOOT_AI_PROVIDER', raising=False)
    # A synthetic empty file only; never read the real .env.
    empty = tmp_path / 'empty.env'
    empty.write_text('')
    assert load_config(empty)['FOOT_AI_PROVIDER'] == 'codex'
    monkeypatch.setenv('FOOT_AI_PROVIDER', 'harness')
    assert load_config(empty)['FOOT_AI_PROVIDER'] == 'harness'
    config = project(tmp_path)
    with pytest.raises(ValueError):
        runtime_provider(config | {'FOOT_AI_PROVIDER': 'claude'})
    path = Path(config['PROJECT_DIR']) / (POLICY_BASE + '.yaml')
    policy = yaml.safe_load(path.read_text())
    policy['runtime_provider'] = 'claude'
    policy['decision']['providers'] = ['claude']
    path.write_text(yaml.safe_dump(policy))
    with pytest.raises(ValueError, match='禁止Claude'):
        active_provider(config['PROJECT_DIR'])


@pytest.mark.parametrize('provider', ['codex', 'harness'])
def test_decision_routes_once_and_never_falls_back(tmp_path, provider):
    config = project(tmp_path, provider)
    calls = []

    def generate(selected, *args, **kwargs):
        calls.append(selected)
        return {'answer': 'offline'}

    envelope = decide(config, tmp_path / 'decision-ok', 'input', {}, lambda x: x, generator=generate)
    assert calls == [provider] and envelope['provider'] == provider
    assert (tmp_path / 'decision-ok' / (provider + '.response.json')).exists()

    def fail(selected, *args, **kwargs):
        calls.append(selected)
        raise ProviderError('unavailable', 'offline')

    with pytest.raises(ProviderError):
        decide(config, tmp_path / 'decision-failed', 'input', {}, lambda x: x, generator=fail)
    assert calls == [provider, provider]
    assert not (tmp_path / 'decision-failed/validated.json').exists()


@pytest.mark.parametrize('provider', ['codex', 'harness'])
def test_artifacts_require_matching_frozen_provider(tmp_path, provider):
    config = project(tmp_path, provider)
    context = {'business_date': '2026-11-04', 'manifest': {'runtime_provider': provider}, 'options': {}, 'slots': {}, 'evidence': []}
    value = {'context_sha256': fingerprint(context), 'summary': 'offline',
             'vetoes': [], 'choices': [], 'assessments': []}
    envelope = decide(config, tmp_path / 'decision-offline', make_decision_prompt(context),
                      DECISION_SCHEMA, lambda x: x, generator=lambda *a, **kw: value)
    (tmp_path / 'ai-decision.json').write_text(json.dumps(envelope))
    (tmp_path / 'decision-context.json').write_text(json.dumps(context))
    assert load_decision(tmp_path) == (envelope, context)
    # Matching hashes alone cannot relabel another provider's output.
    other = 'harness' if provider == 'codex' else 'codex'
    changed = copy.deepcopy(envelope)
    changed['provider'] = other
    changed['attempts'][-1]['provider'] = other
    (tmp_path / 'ai-decision.json').write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='manifest'):
        load_decision(tmp_path)
    (tmp_path / 'ai-decision.json').write_text(json.dumps(envelope))
    (tmp_path / envelope['artifact_dir'] / (provider + '.response.json')).write_text('{}')
    with pytest.raises(ValueError, match='哈希'):
        load_decision(tmp_path)


def test_missing_manifest_and_mixed_attempts_fail_closed(tmp_path):
    config = project(tmp_path)
    context = {'business_date': '2026-11-04', 'manifest': {'runtime_provider': 'codex'}}
    value = {'context_sha256': fingerprint(context), 'summary': 'offline',
             'vetoes': [], 'choices': [], 'assessments': []}
    envelope = decide(config, tmp_path / 'decision-offline', make_decision_prompt(context),
                      DECISION_SCHEMA, lambda x: x, generator=lambda *a, **kw: value)
    envelope['attempts'].insert(0, {'provider': 'claude', 'status': 'failed', 'code': 'timeout'})
    (tmp_path / envelope['artifact_dir'] / 'attempts.json').write_text(json.dumps(envelope['attempts']))
    (tmp_path / 'ai-decision.json').write_text(json.dumps(envelope))
    (tmp_path / 'decision-context.json').write_text(json.dumps(context))
    with pytest.raises(ValueError, match='真实成功'):
        load_decision(tmp_path)
    (tmp_path / 'decision-context.json').write_text('{}')
    with pytest.raises(ValueError, match='manifest'):
        load_decision(tmp_path)
