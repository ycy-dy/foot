"""登录路由、白名单与角色。"""
import secrets
import time
from functools import wraps

import requests
from flask import Blueprint, abort, current_app, g, redirect, render_template, request, session, url_for

from ..core.config import id_set
from .dingtalk import authorize_url, callback_for_origin, redirect_uris

bp = Blueprint('auth', __name__)
PUBLIC = {'auth.login', 'auth.begin', 'auth.callback', 'auth.denied', 'pages.healthz', 'static'}


def configured(config):
    return (all(config.get(k) for k in ('DINGTALK_CLIENT_ID', 'DINGTALK_CLIENT_SECRET', 'DINGTALK_CORP_ID'))
            and bool(redirect_uris(config)))


def role_for(config, user_id):
    if user_id in id_set(config['FOOT_ADMIN_USER_IDS']):
        return 'admin'
    if user_id in id_set(config['FOOT_ALLOWED_USER_IDS']):
        return 'viewer'
    return None


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.user or g.user['role'] != 'admin':
            abort(403)
        return view(*args, **kwargs)
    return wrapper


@bp.before_app_request
def load_user():
    g.user = None
    user = session.get('user')
    cfg = current_app.config['FOOT']
    if user:
        role = role_for(cfg, user['user_id'])  # 白名单移除后立即失效
        if role:
            g.user = user | {'role': role}
        else:
            session.clear()
    if g.user is None and request.endpoint not in PUBLIC:
        if request.path.startswith('/api/'):
            return {'success': False, 'message': '未登录'}, 401
        return redirect(url_for('auth.login'))


@bp.get('/login')
def login():
    if g.user:
        return redirect('/')
    return render_template('login.html', configured=configured(current_app.config['FOOT']), error=request.args.get('error', ''))


@bp.get('/auth/dingtalk/begin')
def begin():
    cfg = current_app.config['FOOT']
    if not configured(cfg):
        return redirect(url_for('auth.login', error='钉钉登录尚未配置'))
    # Only an explicitly configured origin may receive the authorization code.
    callback_uri = callback_for_origin(cfg, request.host_url)
    if callback_uri is None:
        return render_template('login.html', configured=False, error='当前访问地址未配置钉钉回调，请使用已配置的入口登录。'), 400
    state = secrets.token_urlsafe(32)
    session['oauth_state'], session['oauth_started'] = state, time.time()
    session['oauth_redirect_uri'] = callback_uri
    return redirect(authorize_url(cfg, state, callback_uri))


@bp.get('/auth/dingtalk/callback')
def callback():
    cfg, store = current_app.config['FOOT'], current_app.extensions['store']
    expected, started = session.pop('oauth_state', ''), session.pop('oauth_started', 0)
    callback_uri = session.pop('oauth_redirect_uri', '')
    provided = request.args.get('state', '')
    code = request.args.get('authCode') or request.args.get('code')
    ip = request.remote_addr or ''
    if (not expected or not secrets.compare_digest(expected, provided) or time.time() - started > 300 or not code
            or callback_uri != request.base_url or callback_uri not in redirect_uris(cfg)):
        return redirect(url_for('auth.login', error='授权已过期或无效，请重新登录'))
    try:
        identity = current_app.extensions['dingtalk_identity'].exchange(code)
    except (ValueError, KeyError, requests.RequestException) as exc:
        store.event('login_failed', ip=ip, detail={'error': str(exc)[:200]})
        return redirect(url_for('auth.login', error='登录失败：请确认是本企业成员且应用权限正常'))
    role = role_for(cfg, identity['user_id'])
    if not role:
        store.event('login_denied', identity['user_id'], identity['name'], ip)
        session.clear()
        session['denied'] = {'user_id': identity['user_id'], 'name': identity['name']}
        return redirect(url_for('auth.denied'))
    session.clear()
    session.permanent = True
    session['user'] = {'user_id': identity['user_id'], 'name': identity['name']}
    session['csrf'] = secrets.token_urlsafe(24)
    store.event('login', identity['user_id'], identity['name'], ip, {'role': role})
    return redirect('/')


@bp.get('/denied')
def denied():
    info = session.get('denied')
    if not info:
        return redirect(url_for('auth.login'))
    return render_template('denied.html', info=info), 403


@bp.post('/logout')
def logout():
    if request.form.get('csrf') != session.get('csrf'):
        abort(400)
    current_app.extensions['store'].event('logout', g.user['user_id'], g.user['name'], request.remote_addr or '')
    session.clear()
    return redirect(url_for('auth.login'))
