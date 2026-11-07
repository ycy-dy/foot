from conftest import login

def test_security_headers_and_cookie_flag(client, identity, app):
    login(client, identity)
    response=client.get('/')
    assert response.headers['X-Content-Type-Options']=='nosniff'
    assert response.headers['X-Frame-Options']=='DENY'
    assert 'Permissions-Policy' in response.headers
    assert "default-src 'self'" in response.headers['Content-Security-Policy']
    assert 'Strict-Transport-Security' not in response.headers
    assert app.config['SESSION_COOKIE_SECURE'] is False

def test_secure_cookie_opt_in(cfg, identity):
    cfg['FOOT_SECURE_COOKIE']='1'
    from foot_web import create_app
    app=create_app(cfg,identity=identity)
    assert app.config['SESSION_COOKIE_SECURE'] is True


def test_inline_scripts_have_matching_fresh_csp_nonce(client, identity):
    import re
    from test_ui import Elements
    login(client, identity)
    first = client.get('/')
    second = client.get('/')
    first_nonce = re.search(r"'nonce-([^']+)'", first.headers['Content-Security-Policy']).group(1)
    second_nonce = re.search(r"'nonce-([^']+)'", second.headers['Content-Security-Policy']).group(1)
    assert first_nonce != second_nonce
    scripts = [attrs for tag, attrs in Elements(first.get_data(as_text=True)).elements
               if tag == 'script' and not attrs.get('src') and attrs.get('type') != 'application/json']
    assert scripts and all(attrs.get('nonce') == first_nonce for attrs in scripts)
    directive = first.headers['Content-Security-Policy'].split('script-src', 1)[1].split(';', 1)[0]
    assert 'unsafe-inline' not in directive
