from urllib.parse import parse_qs, urlparse

import pytest

from conftest import login

ORIGINS = ('http://192.168.1.4:5020', 'http://100.73.136.41:5020', 'http://172.16.37.247:5020')


def multi_origin(app):
    app.config['FOOT']['DINGTALK_REDIRECT_URIS'] = ','.join(origin + '/auth/dingtalk/callback' for origin in ORIGINS)


@pytest.mark.parametrize('origin', ORIGINS)
def test_login_returns_to_the_same_allowed_origin(app, client, origin):
    multi_origin(app)
    response = client.get('/auth/dingtalk/begin', base_url=origin)
    query = parse_qs(urlparse(response.headers['Location']).query)
    assert query['redirect_uri'] == [origin + '/auth/dingtalk/callback']
    response = client.get('/auth/dingtalk/callback', base_url=origin,
                          query_string={'state': query['state'][0], 'authCode': 'ok'})
    assert response.headers['Location'] == '/'
    assert client.get('/', base_url=origin).status_code == 200


def test_unlisted_host_cannot_influence_oauth_redirect(app, client):
    multi_origin(app)
    response = client.get('/auth/dingtalk/begin', base_url='http://attacker.example:5020')
    assert response.status_code == 400
    assert '未配置' in response.get_data(as_text=True)


def test_forwarded_host_is_not_used_for_redirect(app, client):
    multi_origin(app)
    response = client.get('/auth/dingtalk/begin', base_url=ORIGINS[0],
                          headers={'X-Forwarded-Host': 'attacker.example', 'X-Forwarded-Proto': 'https'})
    query = parse_qs(urlparse(response.headers['Location']).query)
    assert query['redirect_uri'] == [ORIGINS[0] + '/auth/dingtalk/callback']


def test_callback_rejects_changed_origin_and_consumes_state(app, client):
    multi_origin(app)
    client.get('/auth/dingtalk/begin')
    with client.session_transaction() as session:
        state = session['oauth_state']
        session['oauth_redirect_uri'] = ORIGINS[0] + '/auth/dingtalk/callback'
    response = client.get('/auth/dingtalk/callback', query_string={'state': state, 'authCode': 'ok'})
    assert '/login' in response.headers['Location']
    with client.session_transaction() as session:
        assert 'oauth_state' not in session


def test_callback_without_oauth_state_never_logs_in(client):
    assert '/login' in client.get('/auth/dingtalk/callback?authCode=ok').headers['Location']
    assert client.get('/api/today').status_code == 401


def test_login_redirect_config_accepts_multi_address_only(app, client):
    multi_origin(app)
    app.config['FOOT']['DINGTALK_REDIRECT_URI'] = ''
    assert '使用钉钉登录' in client.get('/login').get_data(as_text=True)
    assert client.get('/auth/dingtalk/begin', base_url=ORIGINS[0]).status_code == 302


def test_oauth_state_is_one_use_and_expires(client):
    client.get('/auth/dingtalk/begin')
    with client.session_transaction() as session:
        state = session['oauth_state']
        session['oauth_started'] = 1
    callback = '/auth/dingtalk/callback?state=' + state + '&authCode=ok'
    assert '/login' in client.get(callback).headers['Location']
    assert '/login' in client.get(callback).headers['Location']
    assert client.get('/api/today').status_code == 401


def test_requires_login(client):
    assert client.get('/').headers['Location'].endswith('/login')
    assert client.get('/api/today').status_code == 401
    assert client.get('/healthz').status_code == 200


def test_begin_redirects_to_dingtalk_with_state(client):
    r = client.get('/auth/dingtalk/begin')
    q = parse_qs(urlparse(r.headers['Location']).query)
    assert r.headers['Location'].startswith('https://login.dingtalk.com/oauth2/auth?')
    assert q['client_id'] == ['cid'] and q['corpId'] == ['corp'] and q['scope'] == ['openid corpid']
    with client.session_transaction() as s:
        assert s['oauth_state'] == q['state'][0]


def test_bad_state_rejected(client):
    client.get('/auth/dingtalk/begin')
    r = client.get('/auth/dingtalk/callback?state=wrong&authCode=x')
    assert '/login' in r.headers['Location']


def test_admin_login_and_logout(client, identity):
    r = login(client, identity)
    assert r.headers['Location'] == '/'
    assert client.get('/').status_code == 200
    assert client.get('/admin/events').status_code == 200
    with client.session_transaction() as s:
        csrf = s['csrf']
    assert client.post('/logout', data={'csrf': 'x'}).status_code == 400
    client.post('/logout', data={'csrf': csrf})
    assert client.get('/').status_code == 302


def test_viewer_cannot_open_admin(client, identity):
    login(client, identity, 'viewer1', '只读乙')
    assert client.get('/').status_code == 200
    assert client.get('/admin/events').status_code == 403


def test_not_whitelisted_shows_user_id(client, identity, app):
    r = login(client, identity, 'stranger9', '路人丙')
    assert r.headers['Location'].endswith('/denied')
    page = client.get('/denied').get_data(as_text=True)
    assert 'stranger9' in page and '路人丙' in page
    assert client.get('/').status_code == 302
    assert app.extensions['store'].recent(5)[0]['event'] == 'login_denied'


def test_removed_from_whitelist_loses_access(client, identity, app):
    login(client, identity, 'viewer1', '只读乙')
    app.config['FOOT']['FOOT_ALLOWED_USER_IDS'] = ''
    assert client.get('/').status_code == 302


def test_exchange_failure(client, identity):
    r = login(client, identity, code='bad')
    assert '/login' in r.headers['Location']
