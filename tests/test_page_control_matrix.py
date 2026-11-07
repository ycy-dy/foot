"""Active static pages: local links/forms must resolve and roles stay separated."""
from urllib.parse import urlsplit
import pytest
from conftest import login
from test_ui import Elements

PAGES = ['/', '/daily-ledger', '/history', '/ledger', '/stats', '/research/evaluation',
         '/research/versions', '/analysis', '/reviews', '/automation', '/research/monitoring',
         '/research/notifications', '/admin/events']
ADMIN_ONLY = {'/analysis', '/automation', '/research/monitoring', '/research/notifications', '/admin/events'}


@pytest.mark.parametrize('path', PAGES)
def test_admin_page_controls_have_registered_targets(app, client, identity, path):
    login(client, identity)
    response = client.get(path)
    assert response.status_code == 200
    doc = Elements(response.get_data(as_text=True))
    adapter = app.url_map.bind('localhost')
    for tag, attrs in doc.elements:
        if tag == 'a':
            href = attrs.get('href', '')
            if not href or href.startswith('#') or urlsplit(href).scheme:
                continue
            adapter.match(urlsplit(href).path, method='GET')
        elif tag == 'form':
            target = attrs.get('action') or path
            adapter.match(urlsplit(target).path, method=attrs.get('method', 'get').upper())
        elif tag == 'script' and attrs.get('src', '').startswith('/static/'):
            assert client.get(attrs['src']).status_code == 200


@pytest.mark.parametrize('path', PAGES)
def test_viewer_page_roles_and_no_write_controls(client, identity, path):
    login(client, identity, user_id='viewer1')
    response = client.get(path)
    assert response.status_code == (403 if path in ADMIN_ONLY else 200)
    if response.status_code == 200:
        doc = Elements(response.get_data(as_text=True))
        forms = [a for tag, a in doc.elements if tag == 'form' and a.get('method', '').lower() == 'post']
        assert all(a.get('action') == '/logout' for a in forms)


def test_unavailable_report_and_login_logout_are_explicit(client, identity):
    assert client.get('/').status_code == 302
    login(client, identity)
    assert client.get('/report?date=2000-01-01').status_code == 404
    assert client.post('/logout', data={'csrf': 'bad'}).status_code == 400
    with client.session_transaction() as s:
        csrf = s['csrf']
    assert client.post('/logout', data={'csrf': csrf}).status_code == 302
    assert client.get('/api/stats').status_code == 401
