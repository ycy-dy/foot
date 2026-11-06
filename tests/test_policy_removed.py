"""Current product contract: no active sports analysis/recommendation policy."""
from pathlib import Path

import pytest
from conftest import login
from foot_web.services.versions import rules_manifest
from foot_web.services.publications import PublicationError


def test_manifest_policy_unavailable(cfg):
    manifest, texts = rules_manifest(cfg['PROJECT_DIR'])
    assert manifest['compatibility'] == 'policy_unavailable'
    assert manifest['spec_revision'] == 'policy_removed'
    assert set(texts) == {'AGENTS.md'}
    assert not list(Path(cfg['PROJECT_DIR']).glob('analysis_recommendation_system_v6_0.*'))


def test_removed_pages_and_home(client, identity, app):
    login(client, identity)
    page = client.get('/')
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert '分析与推荐体系已移除' in text
    assert '/systems/analysis' not in text and '/systems/recommendation' not in text
    assert 'system_documents' not in app.extensions
    assert client.get('/systems/analysis').status_code == 404
    assert client.get('/systems/recommendation').status_code == 404
    assert client.get('/healthz').json == {'ok': True}


@pytest.mark.parametrize('path', ['/api/recompute', '/analysis/old/resume', '/research/old/publish', '/automation', '/reviews'])
def test_http_strategy_writes_closed(client, identity, path):
    login(client, identity)
    response = client.post(path, json={})
    assert response.status_code == 409
    assert '体系已删除' in response.json['message']


def test_policy_gate_keeps_role_protection(client, identity):
    login(client, identity, user_id='viewer1')
    assert client.post('/api/recompute').status_code == 403
    assert client.post('/reviews').status_code == 403


def test_background_entrypoints_closed(app, monkeypatch):
    for key, args in [('analysis_tasks', ('2026-11-06', 'admin1')),
                      ('review_tasks', ('2026-11-06', 'admin1')),
                      ('recheck_tasks', ('old-publication', 'admin1'))]:
        with pytest.raises(ValueError, match='体系已删除'):
            app.extensions[key].start(*args)
    with pytest.raises(ValueError, match='体系已删除'):
        app.extensions['analysis_tasks'].resume('old', 'admin1')
    with pytest.raises(PublicationError, match='体系已删除'):
        app.extensions['publications'].check('old', 'admin1')
    def forbidden(*args, **kwargs):
        pytest.fail('must not dispatch stored schedules')
    monkeypatch.setattr(app.extensions['jobs'], 'claim_due', forbidden)
    app.extensions['scheduler'].tick()
