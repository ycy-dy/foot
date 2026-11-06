"""竞彩足球/篮球分析推荐 Web 系统。

分层：core（配置）→ storage（SQLite）→ data（抓取、市场计算）→ services（报告等业务）→ auth / web（路由）。
扩展点（规格 specs/001-web-console）：engine（Claude Agent 任务）、scheduler（定时）、notify（钉钉推送）作为新子包加入，
通过 app.extensions 注册，路由层只依赖 services 接口。
"""
from datetime import timedelta
from pathlib import Path

from flask import Flask, g, session, request

from .auth.dingtalk import DingTalkIdentity
from .auth.routes import bp as auth_bp
from .core.config import load_config
from .data.fetcher import Fetcher
from .engine.tasks import AnalysisTasks
from .engine.review_tasks import ReviewTasks
from .scheduler import Scheduler
from .storage.jobs import JobsStore
from .web.automation import bp as automation_bp
from .services.ledger import Ledger
from .storage.db import Store
from .web.routes import bp as pages_bp
from .web.research import bp as research_bp
from .services.publications import PublicationService
from .web.monitoring import bp as monitoring_bp
from .engine.rechecks import RecheckTasks
from .engine.operations import Operations
from .services.notifications import DingTalkNotifier, Notifications


def pct(p):
    return '—' if p is None else f'{p * 100:.1f}%'


def leg_text(leg):
    opts = '／'.join(f"{o['label']}@{o['odds']}" for o in leg.get('options', []))
    return f"（{leg.get('number', '')}）{leg.get('matchup', '')} {opts}"


def create_app(config=None, fetcher=None, identity=None, analysis_launcher=None):
    cfg = config or load_config()
    if not cfg.get('FOOT_SECRET_KEY'):
        raise RuntimeError('缺少 FOOT_SECRET_KEY（.env）')
    app = Flask(__name__)
    app.secret_key = cfg['FOOT_SECRET_KEY']
    app.config.update(FOOT=cfg, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_NAME='foot_session', PERMANENT_SESSION_LIFETIME=timedelta(days=7))
    app.extensions['store'] = Store(Path(cfg['DATA_DIR']) / 'app.db')
    app.extensions['fetcher'] = fetcher or Fetcher(cfg['DATA_DIR'])
    app.extensions['dingtalk_identity'] = identity or DingTalkIdentity(cfg)
    app.extensions['ledger'] = Ledger(cfg['PROJECT_DIR'], cfg['DATA_DIR'])
    app.extensions['analysis_tasks'] = AnalysisTasks(cfg, app.extensions['store'], analysis_launcher)
    app.extensions['publications'] = PublicationService(cfg, fetcher=app.extensions['fetcher'])
    app.extensions['recheck_tasks'] = RecheckTasks(cfg)
    app.extensions['jobs'] = JobsStore(cfg['DATA_DIR'])
    app.extensions['review_tasks'] = ReviewTasks(cfg, app.extensions['jobs'])
    app.extensions['notifications'] = Notifications(cfg, DingTalkNotifier(
        cfg, token_provider=getattr(app.extensions['dingtalk_identity'], 'corp_token', None)))
    app.extensions['operations'] = Operations(cfg, app.extensions['recheck_tasks'], app.extensions['notifications'])
    app.extensions['scheduler'] = Scheduler(cfg, app.extensions['analysis_tasks'], app.extensions['review_tasks'],
                                            app.extensions['jobs'], app.extensions['operations'])
    app.register_blueprint(automation_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(research_bp)
    app.register_blueprint(monitoring_bp)
    app.jinja_env.filters['pct'] = pct
    app.jinja_env.filters['pctw'] = lambda p: 0 if p is None else round(p * 100, 1)
    app.jinja_env.filters['legtxt'] = leg_text

    @app.before_request
    def removed_policy_guard():
        # The former business policy was explicitly deleted, not replaced.
        if request.method == 'POST' and (
            request.path in ('/api/recompute', '/reviews')
            or request.path.startswith(('/analysis/', '/research/', '/automation'))
        ) and not request.path.endswith('/cancel'):
            if not g.get('user') or g.user.get('role') != 'admin':
                return {'success': False, 'message': '需要管理员权限'}, 403
            return {'success': False, 'message': '分析与推荐体系已删除，策略操作已停用；请先建立新规格'}, 409

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('X-Frame-Options', 'DENY')
        resp.headers.setdefault('Referrer-Policy', 'same-origin')
        return resp

    @app.context_processor
    def inject():
        return {'user': g.get('user'), 'csrf': session.get('csrf', '')}

    return app
