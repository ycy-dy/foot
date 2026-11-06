"""页面与 API 路由：今日仪表盘（多面板）、比赛详情、台账、历史推荐、统计、报告、日志、重新分析。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, abort, current_app, g, jsonify, render_template, request, session

from ..auth.routes import admin_required
from ..data import markets
from ..engine.tasks import output_dir
from ..services import engine
from ..services.drafts import render_draft
from ..services.ledger import GROUPS
from ..services.reports import latest_report

TZ = ZoneInfo('Asia/Shanghai')
bp = Blueprint('pages', __name__)


def load(force=False):
    f = current_app.extensions['fetcher']
    fb_raw, fb_meta = f.get('football', force)
    bk_raw, bk_meta = f.get('basketball', force)
    return markets.parse_football(fb_raw), fb_meta, markets.parse_basketball(bk_raw), bk_meta


def pick_date(fb, bk):
    dates = sorted(set(markets.business_dates(fb)) | set(markets.business_dates(bk)))
    want = request.args.get('date')
    today = datetime.now(TZ).date().isoformat()
    if want in dates:
        return want, dates
    if today in dates:
        return today, dates
    return (dates[0] if dates else today), dates


def ledger():
    return current_app.extensions['ledger']


@bp.get('/healthz')
def healthz():
    return {'ok': True}


@bp.get('/')
def index():
    from ..services.research import exclusion_reason
    try:
        fb, fb_meta, bk, bk_meta = load()
        error = None
    except Exception:
        fb, bk, fb_meta, bk_meta = [], [], {}, {}
        error = '官方赛程及快照不可用，暂不生成推荐'
    bd, dates = pick_date(fb, bk)
    rows = [dict(m) for m in fb + bk if m['business_date'] == bd]
    now = datetime.now(TZ)
    for m in rows:
        m['exclusion'] = exclusion_reason(m, now)
    report = latest_report(current_app.config['FOOT']['PROJECT_DIR'], bd, current_app.config['FOOT']['DATA_DIR'])
    from ..services.dream import published_dream
    dream = published_dream(current_app.extensions['publications'], current_app.config['FOOT'], bd)
    return render_template('recommendation_dashboard.html', dream=dream, bd=bd, week=markets.weekday_label(bd),
                           dates=dates or [bd], matches=rows, error=error, report=report,
                           analysis_task=current_app.extensions['analysis_tasks'].latest(bd)
                           if g.user['role'] == 'admin' else None)


@bp.get('/daily-ledger')
def daily_ledger_view():
    from ..services.daily_ledger import DailyLedgerService
    day = request.args.get('date', datetime.now(TZ).date().isoformat())
    try:
        datetime.strptime(day, '%Y-%m-%d')
    except ValueError:
        abort(400)
    service = DailyLedgerService(current_app.config['FOOT'])
    rows = service.list(day)
    return render_template('daily_ledger.html', bd=day, rows=rows)




@bp.post('/api/recompute')
@admin_required
def recompute():
    if not request.headers.get('X-CSRF') or request.headers.get('X-CSRF') != session.get('csrf'):
        abort(400)
    data = request.get_json(silent=True)
    if data is not None and not isinstance(data, dict):
        abort(400)
    business_date = (data or {}).get('date', datetime.now(TZ).date().isoformat())
    try:
        task, reused = current_app.extensions['analysis_tasks'].start(business_date, g.user['user_id'],
            reuse_from=(data or {}).get('reuse_from'))
    except (ValueError, TypeError):
        return jsonify(success=False, message='业务日须为 YYYY-MM-DD；复用任务必须属于同一业务日'), 400
    current_app.extensions['store'].event('analysis_requested', g.user['user_id'], g.user['name'], request.remote_addr or '',
                                          {'task_id': task['id'], 'date': task['business_date'], 'reused': reused})
    ok = task['status'] != 'failed'
    return jsonify(success=ok, task=task, reused=reused), 202 if ok else 503


@bp.get('/api/analysis/<task_id>')
@admin_required
def analysis_status(task_id):
    task = current_app.extensions['analysis_tasks'].get(task_id)
    if not task:
        abort(404)
    return jsonify(success=True, task=task)


@bp.get('/api/analysis/<task_id>/logs')
@admin_required
def analysis_logs(task_id):
    task = current_app.extensions['analysis_tasks'].get(task_id)
    if not task:
        abort(404)
    try:
        after = int(request.args.get('after', '0'))
        limit = int(request.args.get('limit', '100'))
        if after < 0 or after > 2**63 - 1 or not 1 <= limit <= 200:
            raise ValueError
    except (ValueError, TypeError):
        abort(400)
    rows = current_app.extensions['store'].analysis_logs(task_id, after=after, limit=limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]
    response = jsonify(task=task, logs=rows, next_cursor=rows[-1]['id'] if rows else after, has_more=more)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@bp.get('/api/analysis/<task_id>/logs/download')
@admin_required
def analysis_logs_download(task_id):
    task = current_app.extensions['analysis_tasks'].get(task_id)
    if not task:
        abort(404)
    rows = current_app.extensions['store'].analysis_logs(task_id, limit=2000)
    body = '\n'.join(f'[{row["ts"]}] [{row["provider"]}] [{row["kind"]}] {row["message"]}' for row in rows)
    if not rows:
        body = '此任务未保存过程日志。\n' + task['message']
    return Response(body + '\n', content_type='text/plain; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename="analysis-{task_id}.txt"',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@bp.get('/analysis/<task_id>')
@admin_required
def analysis_view(task_id):
    task = current_app.extensions['analysis_tasks'].get(task_id)
    if not task:
        abort(404)
    draft_html = None
    if task['status'] == 'succeeded':
        path = output_dir(current_app.config['FOOT'], task) / 'report.draft.md'
        if not path.is_file():
            abort(404)
        draft_html = render_draft(path.read_text())
    from .research import item_summary
    items = current_app.extensions['analysis_tasks'].research.items(task_id)
    return render_template('analysis.html', analysis_task=task, draft_html=draft_html,
                           research_items=[item_summary(item) for item in items])


@bp.get('/match/<sport>/<num>')
def match(sport, num):
    if sport not in ('football', 'basketball'):
        abort(404)
    fb, fb_meta, bk, bk_meta = load()
    rows = fb if sport == 'football' else bk
    bd = request.args.get('date')
    hit = [r for r in rows if r['num'] == num and (not bd or r['business_date'] == bd)]
    if not hit:
        abort(404)
    m = hit[0]
    m['options'] = engine.football_options(m) if sport == 'football' else engine.basketball_options(m)
    from ..services.match_analysis import latest_match_analysis
    analysis = latest_match_analysis(current_app.extensions['analysis_tasks'], m,
                                     current_app.config['FOOT'], datetime.now(TZ))
    return render_template('match.html', m=m, meta=fb_meta if sport == 'football' else bk_meta,
                           hafu_lbl=markets.HAFU_LBL, analysis=analysis)


@bp.get('/ledger')
def ledger_view():
    a = request.args
    rows = ledger().query(a.get('from', ''), a.get('to', ''), a.get('group', ''), a.get('kind', ''), a.get('state', ''),
                          a.get('q', '').strip(), a.get('superseded') == '1')
    return render_template('ledger.html', rows=rows, args=a, groups=GROUPS, summary=ledger().summarize(rows), dates=ledger().dates())


@bp.get('/history')
def history_view():
    dates = ledger().dates()
    bd = request.args.get('date') or (dates[0] if dates else '')
    rows = ledger().query(bd, bd, include_superseded=True) if bd else []
    report = latest_report(current_app.config['FOOT']['PROJECT_DIR'], bd, current_app.config['FOOT']['DATA_DIR']) if bd else None
    review = next((task for task in current_app.extensions['review_tasks'].latest()
                   if task['business_date'] == bd), None) if bd else None
    return render_template('history.html', dates=dates, bd=bd, rows=rows, groups=GROUPS, report=report,
                           review_task=review, can_review=bool(rows and bd <= datetime.now(TZ).date().isoformat()),
                           summary=ledger().summarize([r for r in rows if not r['superseded']]))


@bp.get('/stats')
def stats_view():
    months = ledger().months()
    month = request.args.get('month', months[0] if months else '')
    month = '' if month == 'all' else month
    return render_template('stats.html', st=ledger().stats(month), months=months, month=month, groups=GROUPS, all_st=ledger().stats(''))


@bp.get('/report')
def report_view():
    r = latest_report(current_app.config['FOOT']['PROJECT_DIR'], request.args.get('date'), current_app.config['FOOT']['DATA_DIR'])
    if not r:
        abort(404)
    return render_template('report.html', report=r)


@bp.get('/api/today')
def api_today():
    fb, fb_meta, bk, bk_meta = load()
    bd, dates = pick_date(fb, bk)
    return {'success': True, 'business_date': bd, 'dates': dates, 'football_meta': fb_meta, 'basketball_meta': bk_meta,
            'football': [r for r in fb if r['business_date'] == bd], 'basketball': [r for r in bk if r['business_date'] == bd]}


@bp.get('/api/stats')
def api_stats():
    st = ledger().stats(request.args.get('month', ''))
    return {'success': True, 'by_group': st['by_group'], 'by_kind': st['by_kind'], 'total': st['total']}


@bp.get('/admin/events')
@admin_required
def events():
    return render_template('events.html', events=current_app.extensions['store'].recent(100))
