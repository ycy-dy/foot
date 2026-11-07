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
