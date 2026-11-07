"""Legacy editors remain removed; spec014 enables manual evidence-gated research."""
from pathlib import Path

import pytest
from conftest import login
from foot_web.services.versions import RULE_FILES, rules_manifest


def test_manifest_current_policy_enabled_without_legacy_files(cfg):
    manifest, texts = rules_manifest(cfg['PROJECT_DIR'])
    assert manifest['compatibility'] == 'supported_subset'
    assert manifest['evidence_threshold_percent'] == 70
    assert set(texts) == set(RULE_FILES)
    assert not list(Path(cfg['PROJECT_DIR']).glob('analysis_recommendation_system_v6_0.*'))


def test_removed_pages_and_home(client, identity, app):
    login(client, identity)
    page = client.get('/')
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert '70' in text
    assert '/systems/analysis' not in text and '/systems/recommendation' not in text
    assert 'system_documents' not in app.extensions
    assert client.get('/systems/analysis').status_code == 404
    assert client.get('/systems/recommendation').status_code == 404
    assert client.get('/healthz').json == {'ok': True}


@pytest.mark.parametrize('path', ['/automation', '/research/notifications'])
def test_automatic_writes_still_closed(client, identity, path):
    login(client, identity)
    assert client.post(path, json={}).status_code == 400  # CSRF before settings mutation
    with client.session_transaction() as session:
        csrf = session['csrf']
    response = client.post(path, data={'csrf': csrf, 'enabled': '1'})
    assert response.status_code == 403
    assert '尚未获得单独启用授权' in response.get_data(as_text=True)


def test_policy_gate_keeps_role_protection(client, identity):
    login(client, identity, user_id='viewer1')
    assert client.post('/api/recompute').status_code == 403
    assert client.post('/reviews').status_code == 403


def test_manual_entrypoint_enabled_but_stored_schedules_never_dispatch(app, monkeypatch):
    task, reused = app.extensions['analysis_tasks'].start('2026-11-06', 'admin1')
    assert task['status'] == 'queued' and not reused
    def forbidden(*args, **kwargs):
        pytest.fail('must not dispatch stored schedules')
    monkeypatch.setattr(app.extensions['jobs'], 'claim_due', forbidden)
    app.extensions['scheduler'].tick()
