"""A human review feeds a new frozen checkpoint and a new AI decision, never the old ticket."""
import json
from pathlib import Path

from conftest import ANALYSIS_ASOF, audited_research_response, login
from test_publications import researched
from foot_web import create_app
from foot_web.engine.tasks import run_task
from foot_web.services.publications import PublicationService


def test_reviews_feed_new_ai_decision_without_mutating_parent(researched):
    config, tasks, parent, fetcher = researched
    root = Path(config['PROJECT_DIR'])/'runs'/'2026-11-04'/parent['id']
    frozen = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    child, _ = tasks.start('2026-11-04', 'admin1', reuse_from=parent['id'])
    calls = []

    def generate(provider, prompt, *args, **kwargs):
        calls.append(prompt)
        return audited_research_response(prompt)

    run_task(config, child['id'], fetcher=fetcher, generate=generate, as_of=ANALYSIS_ASOF)
    assert tasks.get(child['id'])['status'] == 'succeeded'
    assert calls and all('=== RECOMMENDATION DECISION INPUT ===' in prompt for prompt in calls)
    items = tasks.research.items(child['id'])
    assert any(item['payload'].get('claims') for item in items if item['payload'])
    checked = PublicationService(config, fetcher).check(child['id'], 'admin1', now=ANALYSIS_ASOF)
    assert checked['passed'], checked['errors']
    assert checked['bundle']['groups']
    assert all(path.read_bytes() == content for path, content in frozen.items())
    parent_decision = json.loads((root/'ai-decision.json').read_text())
    assert checked['bundle']['ai_decision']['input_sha256'] != parent_decision['input_sha256']


def test_authenticated_review_uses_actual_actor_and_new_task(researched, identity):
    from foot_web.services.source_provenance import SourceProvenanceStore
    from foot_web.services.evidence_reviews import verified_reviews
    from datetime import datetime
    from zoneinfo import ZoneInfo
    config, tasks, parent, fetcher = researched
    app = create_app(config, fetcher=fetcher, identity=identity, analysis_launcher=lambda *args: None)
    client = app.test_client()
    login(client, identity)
    with client.session_transaction() as session:
        csrf = session['csrf']
    item = tasks.research.items(parent['id'])[0]
    from foot_web.services.research import option_catalog
    source = item['payload']['sources'][0]
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    store = SourceProvenanceStore(Path(config['DATA_DIR'])/'source-provenance')
    text = 'Offline reviewed statement'
    snapshot = store.capture(source['url'], text, now, 'non_odds')
    claim = {'claim_id': 'human-claim', 'claim': text, 'match_id': item['match_key'],
             'option_id': option_catalog(item['match'])[0]['id'], 'dimension_id': 4,
             'source_id': snapshot['source_id'], 'url': source['url'],
             'content_sha256': snapshot['content_sha256'], 'quote': text,
             'locator': {'start': 0, 'end': len(text)}, 'source_type': 'non_odds', 'support_status': 'supports',
             'actor': 'forged-in-claim'}
    response = client.post('/provenance', data={'csrf': csrf, 'action': 'review', 'task_id': parent['id'],
        'claim': json.dumps(claim), 'confirmed': '1', 'actor': 'forged'})
    assert response.status_code == 200
    rows = verified_reviews(config['DATA_DIR'], parent['id'], item['match_key'],
                            datetime.now(ZoneInfo('Asia/Shanghai')), {'admin1'})
    assert any(row['claim']['claim_id'] == 'human-claim' for row in rows)
    from foot_web.services.evidence_reviews import reviewed_evidence
    derived = reviewed_evidence(config['DATA_DIR'], parent['id'], 'child-checkpoint', item,
                                datetime.now(ZoneInfo('Asia/Shanghai')), {'admin1'})
    assert derived['claims'] and all('actor' not in row and 'task_id' not in row for row in derived['claims'])
    response = client.post('/provenance', data={'csrf': csrf, 'action': 'reanalyze', 'task_id': parent['id']})
    assert response.status_code == 303 and parent['id'] not in response.location
    login(client, identity, user_id='viewer1')
    assert client.post('/provenance', data={'csrf': csrf, 'action': 'reanalyze', 'task_id': parent['id']}).status_code == 403


def test_self_reported_receipt_strings_never_create_runtime_candidates(cfg):
    from conftest import FakeFetcher, audited_research_payload
    from foot_web.engine.tasks import prepare_input
    from foot_web.services.evidence_reviews import runtime_items
    from foot_web.services.research import match_key
    from foot_web.services.selection import decision_context
    from foot_web.services.versions import rules_manifest
    source = prepare_input(cfg, {'business_date': '2026-11-04'}, FakeFetcher(), ANALYSIS_ASOF)
    source['football'], source['basketball'] = source['football'][:2], []
    items = [{'match_key': match_key(match), 'match': match, 'status': 'succeeded',
              'payload': audited_research_payload(match)} for match in source['football']]
    items = runtime_items(cfg, 'no-real-task', items, ANALYSIS_ASOF)
    context = decision_context(source, items, rules_manifest(cfg['PROJECT_DIR'])[0], ANALYSIS_ASOF)
    assert not context['options']
