"""Authenticated manual provenance actions; never auto-certifies AI claims."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, g, redirect, render_template, request
from ..auth.routes import admin_required
from ..services.source_provenance import SourceProvenanceStore, ProvenanceError
from .research import csrf_check

bp = Blueprint('provenance', __name__)


@bp.route('/provenance', methods=['GET', 'POST'])
@admin_required
def manual_review():
    result, error, status = None, None, 200
    if request.method == 'POST':
        csrf_check()
        if request.content_length and request.content_length > 2_200_000:
            abort(413)
        store = SourceProvenanceStore(Path(current_app.config['FOOT']['DATA_DIR']).resolve() / 'source-provenance')
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        try:
            if request.form.get('action') == 'reanalyze':
                task_id = request.form.get('task_id', '').strip()
                task = current_app.extensions['analysis_tasks'].get(task_id)
                if not task or task.get('status') not in ('succeeded', 'partial'):
                    raise ProvenanceError('必须选择已保存检查点的研究任务')
                new, _ = current_app.extensions['analysis_tasks'].start(task['business_date'], g.user['user_id'], reuse_from=task_id)
                return redirect(new['result_url'], code=303)
            if request.form.get('action') == 'capture':
                result = store.capture(request.form.get('url', ''), request.form.get('text', ''), now, 'non_odds')
            elif request.form.get('action') == 'review':
                if request.form.get('confirmed') != '1':
                    raise ProvenanceError('请逐项确认原文、引用、比赛与选项的实际支持关系')
                claim = json.loads(request.form.get('claim', ''))
                if not isinstance(claim, dict):
                    raise ProvenanceError('claim必须为JSON对象')
                task_id = request.form.get('task_id', '').strip()
                if not task_id:
                    raise ProvenanceError('必须绑定真实研究任务，不能只提交自由文本claim')
                task = current_app.extensions['analysis_tasks'].get(task_id)
                if not task or task.get('status') not in ('succeeded', 'partial'):
                    raise ProvenanceError('研究任务不存在或尚未保存检查点')
                item = next((x for x in current_app.extensions['analysis_tasks'].research.items(task_id)
                             if x['match_key'] == claim.get('match_id')), None)
                if item is None:
                    raise ProvenanceError('claim比赛身份不属于该研究任务')
                from ..services.research import option_catalog
                option_ids = {option['id'] for option in option_catalog(item['match'])}
                if claim.get('option_id') not in option_ids:
                    raise ProvenanceError('claim选项不属于该比赛')
                if claim.get('url') not in {source['url'] for source in (item.get('payload') or {}).get('sources', [])}:
                    raise ProvenanceError('claim来源未出现在该场冻结研究中')
                claim['task_id'] = task_id
                quote = store.check_quote(claim, as_of=now, match_id=claim.get('match_id', ''),
                                          option_id=claim.get('option_id', ''), dimension_id=claim.get('dimension_id'))
                reviewed = store.record_manual_review(quote['receipt_id'], actor=g.user['user_id'], reviewed_at=now)
                from ..services.evidence_reviews import save_review
                save_review(current_app.config['FOOT']['DATA_DIR'], task_id, claim,
                            quote['receipt_id'], reviewed['receipt_id'])
                result = {'quote_receipt_id': quote['receipt_id'], 'manual_review_receipt_id': reviewed['receipt_id'],
                          'verified': store.verify_support(claim, quote_receipt_id=quote['receipt_id'],
                              manual_review_receipt_id=reviewed['receipt_id'], as_of=now,
                              match_id=claim['match_id'], option_id=claim['option_id'], dimension_id=claim['dimension_id'])['verified']}
            else:
                abort(400)
            current_app.extensions['store'].event('source_provenance_' + request.form['action'], g.user['user_id'],
                                                  detail={'artifact_id': result.get('source_id') or result.get('manual_review_receipt_id')})
        except (ProvenanceError, ValueError, KeyError, TypeError):
            error, status = '原文、引用或身份绑定无效，未生成有效复核；请核对输入。', 400
    response = current_app.make_response((render_template('provenance.html', result=result, error=error), status))
    response.headers['Cache-Control'] = 'private, no-store'
    return response
