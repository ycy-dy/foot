"""Research performance and operational monitoring without automatic external actions."""
import re
import os
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for

from ..services.evaluation import Evaluation
from ..services.ledger import GROUPS
from ..auth.routes import admin_required
from ..core.privacy import redact, secret_values
from ..services.notifications import allowed_origins
from .automation import AUTOMATION_DISABLED_REASON, management_controls

bp = Blueprint('monitoring', __name__)
TZ = ZoneInfo('Asia/Shanghai')


def csrf_check():
    expected = session.get('csrf') or ''
    provided = request.form.get('csrf') or request.headers.get('X-CSRF') or ''
    if not expected or not provided or not secrets.compare_digest(expected, provided):
        abort(400)


def rechecks():
    return current_app.extensions['recheck_tasks']


def notifications():
    return current_app.extensions['notifications']


@bp.after_request
def private(response):
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@bp.get('/research/evaluation')
def evaluation():
    month = request.args.get('month', '')
    group = request.args.get('group', '最终推荐')
    unit = request.args.get('unit', 'ticket')
    sport = request.args.get('sport', 'all')
    if (month and not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])', month) or group not in GROUPS
            or unit not in ('ticket', 'leg') or sport not in ('all', 'football', 'basketball')):
        abort(400)
    evaluator = Evaluation(current_app.config['FOOT'], current_app.extensions['ledger'],
                           current_app.extensions['publications'].store)
    result = evaluator.report(month=month, group=group, unit=unit, sport=sport)
    return render_template('evaluation.html', evaluation=result, groups=GROUPS,
                           months=current_app.extensions['ledger'].months())


@bp.get('/research/monitoring')
@admin_required
def monitoring():
    store = rechecks().store
    return render_template('monitoring.html', settings=store.preferences(), tasks=store.list())


@bp.post('/research/monitoring')
@admin_required
def monitoring_settings():
    csrf_check()
    if request.form.get('enabled') == '1':
        return render_template('monitoring.html', settings=rechecks().store.preferences(),
                               tasks=rechecks().store.list(), error=AUTOMATION_DISABLED_REASON), 403
    try:
        rechecks().store.save_preferences(request.form, g.user['user_id'])
    except ValueError as exc:
        return render_template('monitoring.html', settings=rechecks().store.preferences(),
                               tasks=rechecks().store.list(), error=str(exc)), 400
    rechecks().store.store.event('monitoring_settings_saved', g.user['user_id'])
    return redirect(url_for('monitoring.monitoring', saved='1'), code=303)


@bp.post('/publications/<publication_id>/recheck')
@admin_required
def request_recheck(publication_id):
    csrf_check()
    controls = management_controls()
    if not controls['policy_available']:
        abort(409, description=controls['policy_disabled_reason'])
    try:
        task, _ = rechecks().start(publication_id, g.user['user_id'], lineup_enabled=request.form.get('lineup_enabled') == '1')
    except KeyError:
        abort(404)
    except ValueError as exc:
        abort(409, description=str(exc))
    return redirect(url_for('monitoring.recheck_view', task_id=task['id']), code=303)


@bp.post('/publications/<publication_id>/withdraw')
@admin_required
def withdraw(publication_id):
    csrf_check()
    reason = redact(request.form.get('reason', ''), secret_values(current_app.config['FOOT'], os.environ), limit=500)
    try:
        current_app.extensions['publications'].store.withdraw(publication_id, g.user['user_id'],
                                                            reason, datetime.now(TZ))
    except KeyError:
        abort(404)
    except ValueError as exc:
        abort(409, description=str(exc))
    return redirect(url_for('research.publication_view', publication_id=publication_id), code=303)


@bp.get('/rechecks/<task_id>')
def recheck_view(task_id):
    task = rechecks().get(task_id)
    if not task:
        abort(404)
    return render_template('recheck.html', task=task, result=task['payload'])


@bp.post('/rechecks/<task_id>/cancel')
@admin_required
def cancel_recheck(task_id):
    csrf_check()
    task = rechecks().get(task_id)
    if not task:
        abort(404)
    if task['status'] == 'queued':
        rechecks().store.update(task_id, status='cancelled', cancel_requested=1, message='已取消排队复核',
                               finished_at=datetime.now(TZ).isoformat())
    elif task['status'] == 'running':
        rechecks().store.update(task_id, cancel_requested=1, message='正在取消并清理CLI进程')
    return redirect(url_for('monitoring.recheck_view', task_id=task_id), code=303)


@bp.get('/api/rechecks/<task_id>')
def recheck_status(task_id):
    task = rechecks().get(task_id)
    if not task:
        abort(404)
    try:
        cursor = int(request.args.get('after', '0'))
        if not 0 <= cursor <= 2**63-1:
            raise ValueError
    except ValueError:
        abort(400)
    logs = rechecks().store.store.analysis_logs(task_id, after=cursor, limit=101) if g.user['role'] == 'admin' else []
    more, logs = len(logs) > 100, logs[:100]
    public = {key: task[key] for key in ('id', 'publication_id', 'status', 'message', 'updated_at', 'finished_at')}
    public['result_ready'] = task['payload'] is not None
    return jsonify(task=public, logs=logs, next_cursor=logs[-1]['id'] if logs else cursor, has_more=more)


def notification_page(error=None, status=200):
    notifier = notifications()
    ready, reason = notifier.readiness()
    return render_template('notifications.html', settings=notifier.store.preferences(), ready=ready,
                           readiness=reason, origins=allowed_origins(current_app.config['FOOT']),
                           recipients=notifier.recipients(), rows=notifier.store.list(), error=error), status


@bp.get('/research/notifications')
@admin_required
def notification_view():
    return notification_page()


@bp.post('/research/notifications')
@admin_required
def notification_settings():
    csrf_check()
    if request.form.get('enabled') == '1':
        return notification_page(AUTOMATION_DISABLED_REASON, 403)
    try:
        notifications().save_preferences(request.form, g.user['user_id'])
    except ValueError as exc:
        return notification_page(str(exc), 400)
    return redirect(url_for('monitoring.notification_view', saved='1'), code=303)


@bp.post('/research/notifications/test')
@admin_required
def notification_test():
    csrf_check()
    return notification_page(AUTOMATION_DISABLED_REASON, 403)
