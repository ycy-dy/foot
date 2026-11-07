"""Analysis checkpoints and research UI. Mutations are administrator-only."""
import secrets

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for
import json
from pathlib import Path
import requests

from ..auth.routes import admin_required
from ..services.research import DIMENSIONS, STATUSES
from ..services.versions import rules_manifest
from ..services.publications import PublicationError
from ..services.drafts import render_draft

bp = Blueprint('research', __name__)


def csrf_check():
    provided = request.headers.get('X-CSRF') or request.form.get('csrf') or ''
    expected = session.get('csrf') or ''
    if not provided or not expected or not secrets.compare_digest(provided, expected):
        abort(400)


def tasks():
    return current_app.extensions['analysis_tasks']


@bp.after_request
def private(response):
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@bp.get('/analysis')
@admin_required
def task_list():
    with tasks().store.connect() as db:
        rows = db.execute('SELECT * FROM analysis_runs ORDER BY created_at DESC LIMIT 60').fetchall()
    return render_template('analysis_list.html', tasks=[tasks().present(dict(row)) for row in rows])


@bp.post('/api/analysis/<task_id>/<action>')
@admin_required
def control(task_id, action):
    if action not in ('cancel', 'resume'):
        abort(404)
    csrf_check()
    try:
        if action == 'cancel':
            task = tasks().cancel(task_id, g.user['user_id'])
            reused = False
        else:
            task, reused = tasks().resume(task_id, g.user['user_id'])
    except KeyError:
        abort(404)
    except ValueError as exc:
        return jsonify(success=False, message=str(exc)), 409
    return jsonify(success=True, task=task, reused=reused)


def item_summary(item):
    match, payload = item['match'], item['payload']
    return {
        'match_key': item['match_key'], 'sport': item['sport'], 'num': item['num'],
        'home': match['home'], 'away': match['away'], 'league': match['league'], 'kickoff': match['kickoff'],
        'status': item['status'], 'message': item['message'], 'as_of': item['as_of'],
        'sources': len((payload or {}).get('sources') or []),
        'verified': sum(d.get('status') == 'verified' for d in ((payload or {}).get('dimensions') or []) if isinstance(d, dict)),
        'url': f'/analysis/{item["task_id"]}/matches/{item["match_key"]}',
    }


@bp.get('/api/analysis/<task_id>/matches')
@admin_required
def match_status(task_id):
    task = tasks().get(task_id)
    if not task:
        abort(404)
    items = tasks().research.items(task_id)
    return jsonify(task=task, matches=[item_summary(item) for item in items])


@bp.get('/analysis/<task_id>/matches/<match_id>')
@admin_required
def evidence(task_id, match_id):
    task = tasks().get(task_id)
    if not task:
        abort(404)
    item = next((i for i in tasks().research.items(task_id) if i['match_key'] == match_id), None)
    if item is None:
        abort(404)
    from ..services.recommendations import options_with_evidence
    from datetime import datetime
    from zoneinfo import ZoneInfo
    scored_options = options_with_evidence(item['match'], item, datetime.now(ZoneInfo('Asia/Shanghai')))
    return render_template('evidence.html', scored_options=scored_options, analysis_task=task, item=item, m=item['match'],
                           evidence=item['payload'], dimensions=DIMENSIONS, statuses=STATUSES)


@bp.get('/research/versions')
def versions():
    try:
        manifest, _ = rules_manifest(current_app.config['FOOT']['PROJECT_DIR'])
        error = None
    except (ValueError, OSError, KeyError, TypeError) as exc:
        manifest, error = None, '无法读取或验证现行规则：' + type(exc).__name__
    return render_template('research_versions.html', manifest=manifest, error=error)


def publications():
    return current_app.extensions['publications']


def review_page(task_id, error=None, status=200):
    task = tasks().get(task_id)
    if not task:
        abort(404)
    try:
        _, _, _, draft = publications().draft(task_id)
    except (PublicationError, OSError, ValueError):
        draft = None
    checked = publications().store.latest_check(task_id)
    return render_template('analysis_review.html', analysis_task=task, draft=draft, checked=checked,
                           error=error, bundle=checked['bundle'] if checked else draft), status


@bp.get('/analysis/<task_id>/review')
@admin_required
def audit_view(task_id):
    return review_page(task_id)


@bp.post('/analysis/<task_id>/review')
@admin_required
def audit_action(task_id):
    csrf_check()
    try:
        action = request.form.get('action')
        if action == 'audit':
            publications().check(task_id, g.user['user_id'])
            return redirect(url_for('research.audit_view', task_id=task_id), code=303)
        if action == 'publish':
            publication, _ = publications().publish(task_id, request.form.get('check_id', ''),
                g.user['user_id'], confirmed=request.form.get('confirmed') == 'on')
            return redirect(url_for('research.publication_view', publication_id=publication['id']), code=303)
        abort(400)
    except KeyError:
        abort(404)
    except PublicationError as exc:
        return review_page(task_id, error=str(exc), status=409)
    except (OSError, ValueError, requests.RequestException) as exc:
        current_app.logger.exception('Research audit/publication failed')
        return review_page(task_id, error='审核或保存未完成，未推广新版本：' + type(exc).__name__, status=503)


def _publication_diff(previous, current):
    from ..storage.publications import ticket_slot
    def index(rows):
        return {(ticket_slot(row), row['title']): row for row in rows}
    before, after = index(previous), index(current)
    out = []
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        if old is None:
            kind = '新增'
        elif new is None:
            kind = '移除'
        elif old['legs'] != new['legs']:
            kind = '方向、价格或证据变化'
        else:
            continue
        out.append({'kind': kind, 'title': key[1], 'before': old, 'after': new})
    return out


@bp.get('/publications/<publication_id>')
def publication_view(publication_id):
    publication = publications().store.get(publication_id)
    if not publication:
        abort(404)
    root = Path(current_app.config['FOOT']['PROJECT_DIR']) / 'runs' / publication['business_date'] / publication['id']
    path = root / 'report.md'
    if not path.is_file():
        abort(404)
    previous = publications().store.get(publication['previous_id']) if publication['previous_id'] else None
    current_tickets = json.loads((root / 'tickets.json').read_text())
    previous_tickets = []
    if previous:
        previous_path = root.parent / previous['id'] / 'tickets.json'
        if previous_path.is_file():
            previous_tickets = json.loads(previous_path.read_text())
    active = publications().store.current(publication['business_date'])
    recheck_records = current_app.extensions['recheck_tasks'].store.list(publication_id)
    return render_template('publication.html', publication=publication, previous=previous,
                           active=bool(active and active['id'] == publication['id'] and active['status'] == 'published'),
                           latest_recheck=recheck_records[0] if recheck_records else None,
                           report_html=render_draft(path.read_text()),
                           changes=_publication_diff(previous_tickets, current_tickets))
