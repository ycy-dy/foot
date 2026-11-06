"""定时计划管理与独立复盘页面。"""
import secrets
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for

from ..auth.routes import admin_required
from ..services.drafts import render_draft

bp = Blueprint('automation', __name__)
TZ = ZoneInfo('Asia/Shanghai')


def csrf_check():
    supplied = request.form.get('csrf', '')
    expected = session.get('csrf', '')
    if not supplied or not expected or not secrets.compare_digest(supplied, expected):
        abort(400)


def jobs():
    return current_app.extensions['jobs']


def review_tasks():
    return current_app.extensions['review_tasks']


@bp.after_request
def private(response):
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@bp.get('/automation')
@admin_required
def schedules():
    fires = jobs().fires()
    for fire in fires:
        if fire['task_id']:
            if fire['kind'] == 'analysis':
                task = current_app.extensions['analysis_tasks'].get(fire['task_id'])
                fire['url'] = url_for('pages.analysis_view', task_id=fire['task_id'])
            else:
                task = review_tasks().get(fire['task_id'])
                fire['url'] = url_for('automation.review_detail', task_id=fire['task_id'])
            fire['task_status'] = task['status'] if task else 'unknown'
    return render_template('automation.html', schedules=jobs().schedules(), fires=fires,
                           saved=request.args.get('saved') == '1')


@bp.post('/automation')
@admin_required
def save_schedule():
    csrf_check()
    try:
        row = jobs().save_schedule(request.form, g.user['user_id'])
    except ValueError as exc:
        return render_template('automation.html', schedules=jobs().schedules(), fires=jobs().fires(),
                               error=str(exc), submitted=request.form), 400
    jobs().store.event('schedule_saved', g.user['user_id'], g.user['name'], request.remote_addr or '',
                       {'id': row['id'], 'enabled': bool(row['enabled']), 'kind': row['kind']})
    return redirect(url_for('automation.schedules', saved='1'), code=303)


@bp.get('/reviews')
def reviews():
    return render_template('reviews.html', tasks=review_tasks().latest(), dates=current_app.extensions['ledger'].dates(),
                           default_date=(datetime.now(TZ).date() - timedelta(days=1)).isoformat())


@bp.post('/reviews')
@admin_required
def request_review():
    csrf_check()
    try:
        task, reused = review_tasks().start(request.form.get('date'), g.user['user_id'])
    except (ValueError, TypeError):
        return render_template('reviews.html', tasks=review_tasks().latest(), dates=current_app.extensions['ledger'].dates(),
                               default_date=request.form.get('date', ''), error='业务日须为 YYYY-MM-DD'), 400
    jobs().store.event('review_requested', g.user['user_id'], g.user['name'], request.remote_addr or '',
                       {'task_id': task['id'], 'date': task['business_date'], 'reused': reused})
    if request.form.get('origin') == 'history' and task['business_date'] == request.form.get('date'):
        return redirect(url_for('pages.history_view', date=task['business_date']), code=303)
    return redirect(url_for('automation.review_detail', task_id=task['id']), code=303)


@bp.get('/reviews/<task_id>')
def review_detail(task_id):
    task = review_tasks().get(task_id)
    if not task:
        abort(404)
    html = None
    mode = None
    if task['status'] == 'succeeded':
        path = Path(current_app.config['FOOT']['PROJECT_DIR']) / 'runs' / task['business_date'] / task['id'] / 'review.md'
        if not path.is_file():
            abort(404)
        html = render_draft(path.read_text())
        manifest = path.with_name('manifest.json')
        mode = json.loads(manifest.read_text()).get('analysis_mode') if manifest.is_file() else 'legacy'
    return render_template('review.html', task=task, review_html=html, review_mode=mode)


@bp.get('/api/reviews/<task_id>')
def review_status(task_id):
    task = review_tasks().get(task_id)
    if not task:
        abort(404)
    try:
        cursor = int(request.args.get('after', '0'))
        if not 0 <= cursor <= 2**63-1:
            raise ValueError
    except ValueError:
        abort(400)
    logs = jobs().store.analysis_logs(task_id, after=cursor, limit=101) if g.user['role'] == 'admin' else []
    more, logs = len(logs) > 100, logs[:100]
    public = {key: task[key] for key in ('id', 'business_date', 'status', 'message', 'updated_at', 'finished_at')}
    path = Path(current_app.config['FOOT']['PROJECT_DIR']) / 'runs' / task['business_date'] / task['id'] / 'review.md'
    public['result_ready'] = task['status'] == 'succeeded' and path.is_file()
    return jsonify(task=public, logs=logs, next_cursor=logs[-1]['id'] if logs else cursor, has_more=more)
