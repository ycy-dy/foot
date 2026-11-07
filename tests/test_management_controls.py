"""Management button contracts; isolated fixtures and launch/send doubles only."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from conftest import login


def csrf(client):
    with client.session_transaction() as session:
        return session['csrf']


@pytest.mark.parametrize('url', ['/automation', '/research/notifications', '/research/monitoring'])
def test_management_pages_explain_disabled_automation(client, identity, url):
    login(client, identity)
    response = client.get(url)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '尚未获得单独启用授权' in html
    assert 'name="enabled" value="1" disabled' in html
    assert 'name="csrf"' in html


@pytest.mark.parametrize('url', ['/automation', '/research/notifications', '/research/monitoring',
                                 '/research/notifications/test'])
def test_viewer_cannot_change_management_controls(client, identity, url):
    login(client, identity, 'viewer1')
    assert client.post(url, data={'csrf': csrf(client), 'enabled': '1'}).status_code == 403


@pytest.mark.parametrize('url', ['/research/monitoring', '/research/notifications/test', '/reviews',
                                 '/publications/missing/recheck', '/publications/missing/withdraw',
                                 '/rechecks/missing/cancel'])
def test_management_mutations_require_csrf(client, identity, url):
    login(client, identity)
    assert client.post(url).status_code == 400


def test_forged_automatic_enable_does_not_change_state(app, client, identity):
    login(client, identity)
    token = csrf(client)
    for url in ['/research/monitoring', '/research/notifications', '/automation']:
        response = client.post(url, data={'csrf': token, 'enabled': '1'})
        assert response.status_code in (403, 409)
    assert not app.extensions['recheck_tasks'].store.preferences()['enabled']
    assert not app.extensions['notifications'].store.preferences()['enabled']
    assert not app.extensions['jobs'].schedules()


def test_disabled_settings_can_be_saved_without_starting_work(app, client, identity):
    login(client, identity)
    token = csrf(client)
    forms = [('/automation', {'name': '隔离停用计划', 'kind': 'review', 'time': '12:00', 'offset': '-1'}),
             ('/research/notifications', {'origin': ''}),
             ('/research/monitoring', {'lead_minutes': '60', 'interval_minutes': '15'})]
    for url, fields in forms:
        response = client.post(url, data=fields | {'csrf': token})
        assert response.status_code == 303
        assert 'saved=1' in response.location
        assert client.get(response.location).status_code == 200
    assert not app.extensions['jobs'].schedules()[0]['enabled']
    assert not app.extensions['notifications'].store.preferences()['enabled']
    assert not app.extensions['recheck_tasks'].store.preferences()['enabled']


def test_test_notification_never_enqueues_without_authorization(app, client, identity, monkeypatch):
    login(client, identity)
    enqueue = Mock(side_effect=AssertionError('must not enqueue external messages'))
    monkeypatch.setattr(app.extensions['notifications'], 'enqueue', enqueue)
    response = client.post('/research/notifications/test', data={'csrf': csrf(client)})
    assert response.status_code == 403
    assert '尚未获得单独启用授权' in response.get_data(as_text=True)
    enqueue.assert_not_called()


def test_review_start_is_explicit_and_mocked(app, client, identity, monkeypatch):
    login(client, identity)
    start = Mock(return_value=({'id': 'mock-review', 'business_date': '2026-11-05'}, False))
    monkeypatch.setattr(app.extensions['review_tasks'], 'start', start)
    response = client.post('/reviews', data={'csrf': csrf(client), 'date': '2026-11-05'})
    assert response.status_code == 303
    assert response.location.endswith('/reviews/mock-review')
    start.assert_called_once_with('2026-11-05', 'admin1')


def test_manual_recheck_and_withdraw_use_explicit_routes_only(app, client, identity, monkeypatch):
    login(client, identity)
    start = Mock(return_value=({'id': 'mock-recheck'}, False))
    withdraw = Mock()
    monkeypatch.setattr(app.extensions['recheck_tasks'], 'start', start)
    monkeypatch.setattr(app.extensions['publications'].store, 'withdraw', withdraw)
    response = client.post('/publications/mock-publication/recheck',
                           data={'csrf': csrf(client), 'lineup_enabled': '1'})
    assert response.status_code == 303
    assert response.location.endswith('/rechecks/mock-recheck')
    start.assert_called_once_with('mock-publication', 'admin1', lineup_enabled=True)
    response = client.post('/publications/mock-publication/withdraw',
                           data={'csrf': csrf(client), 'reason': '离线测试撤销'})
    assert response.status_code == 303
    assert withdraw.call_args.args[:3] == ('mock-publication', 'admin1', '离线测试撤销')


def test_policy_unavailable_disables_review_and_blocks_manual_recheck(app, client, identity, monkeypatch):
    login(client, identity)
    Path(app.config['FOOT']['PROJECT_DIR'], 'specs/014-evidence-gated-recommendations/policy.yaml').unlink()
    response = client.get('/reviews')
    html = response.get_data(as_text=True)
    assert 'disabled aria-describedby="review-policy-disabled"' in html
    assert '当前政策或证据评分契约不可用' in html
    start = Mock()
    monkeypatch.setattr(app.extensions['recheck_tasks'], 'start', start)
    assert client.post('/publications/mock/recheck', data={'csrf': csrf(client)}).status_code == 409
    start.assert_not_called()


def test_cancel_queued_recheck_and_invalid_cursor(app, client, identity, monkeypatch):
    login(client, identity)
    task = {'id': 'mock', 'status': 'queued'}
    monkeypatch.setattr(app.extensions['recheck_tasks'], 'get', lambda task_id: task)
    update = Mock()
    monkeypatch.setattr(app.extensions['recheck_tasks'].store, 'update', update)
    response = client.post('/rechecks/mock/cancel', data={'csrf': csrf(client)})
    assert response.status_code == 303
    assert update.call_args.kwargs['status'] == 'cancelled'
    assert client.get('/api/rechecks/mock?after=-1').status_code == 400


def test_polling_handles_expired_login_and_missing_tasks():
    static = Path(__file__).parents[1] / 'src/foot_web/static'
    for name in ('reviews.js', 'rechecks.js'):
        script = (static / name).read_text()
        assert 'response.redirected' in script
        assert 'response.status === 404' in script
        assert 'encodeURIComponent' in script
        assert 'pagehide' in script
