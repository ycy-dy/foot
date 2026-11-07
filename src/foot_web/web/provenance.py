"""Authenticated manual provenance actions; never auto-certifies AI claims."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, g, render_template, request
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
            if request.form.get('action') == 'capture':
                result = store.capture(request.form.get('url', ''), request.form.get('text', ''), now, 'non_odds')
            elif request.form.get('action') == 'review':
                if request.form.get('confirmed') != '1':
                    raise ProvenanceError('请逐项确认原文、引用、比赛与选项的实际支持关系')
                claim = json.loads(request.form.get('claim', ''))
                quote = store.check_quote(claim, as_of=now, match_id=claim.get('match_id', ''),
                                          option_id=claim.get('option_id', ''), dimension_id=claim.get('dimension_id'))
                reviewed = store.record_manual_review(quote['receipt_id'], actor=g.user['user_id'], reviewed_at=now)
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
