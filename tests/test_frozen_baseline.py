"""026 real publication→frozen benchmark→read-only evaluation contract."""
import copy
import json
from pathlib import Path

import pytest

from conftest import ANALYSIS_ASOF
from test_publications import researched  # Real offline workflow fixture, no build_bundle patch.
from foot_web.services.evaluation import Evaluation
from foot_web.services.evaluation_baseline import freeze_baseline, validate_baseline
from foot_web.services.publications import PublicationService, fresh_input
from foot_web.services.research import fingerprint
from foot_web.services.reviews import settle


def test_publication_to_evaluation_reads_frozen_market_benchmark(researched):
    config, _, task, fetcher = researched
    service = PublicationService(config, fetcher)
    checked = service.check(task['id'], 'admin1', now=ANALYSIS_ASOF)
    assert checked['passed'], checked['errors']
    baseline = checked['baseline']
    assert baseline['tickets'] and baseline['label'] == 'market benchmark not advice'
    publication, _ = service.publish(task['id'], checked['id'], 'admin1', confirmed=True, now=ANALYSIS_ASOF)
    folder = Path(publication['folder'])
    frozen = json.loads((folder / 'baseline.json').read_text())
    audit = json.loads((folder / 'audit.json').read_text())
    assert frozen['content_sha256'] == publication['baseline_sha256']
    assert validate_baseline(frozen, publication, audit) == frozen['tickets']
    # Settlement uses the exact same standard ticket shape as published AI tickets.
    results = {'football': [], 'basketball': []}
    for ticket in frozen['tickets']:
        for leg in ticket['legs']:
            results[leg['sport']].append({'matchNumStr': leg['number'], 'matchDate': leg['match_date'],
                'allHomeTeam': leg['home'], 'allAwayTeam': leg['away'],
                **({'matchResultStatus': '2', 'sectionsNo999': '2:1', 'sectionsNo1': '1:0'}
                   if leg['sport'] == 'football' else {'status': 2, 'finalScore': '100-110'})})
        assert 'hit' in settle(ticket, results)
    review = folder.parent / 'review-frozen'
    review.mkdir()
    (review / 'results.json').write_text(json.dumps(results))
    with service.store.store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS review_current(date TEXT PRIMARY KEY,run_id TEXT,payload TEXT)')
        db.execute('INSERT INTO review_current VALUES(?,?,?)', (
            publication['business_date'], review.name, json.dumps({'run_id': review.name})))
    before = {p: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    report = Evaluation(config, None, service.store).paired_comparison()
    assert not report['gaps']
    assert report['baseline_available'] == len(frozen['tickets']) > 0
    assert report['matched_periods'] > 0
    assert all(p.read_bytes() == value for p, value in before.items())
    # Removal is not repaired or silently recomputed from the still-valid audit.
    (folder / 'baseline.json').unlink()
    missing = Evaluation(config, None, service.store).paired_comparison()
    assert missing['gaps'] and missing['baseline_available'] == 0
    assert not (folder / 'baseline.json').exists()


def test_market_only_baseline_does_not_require_ai_or_evidence(researched):
    config, _, task, fetcher = researched
    service = PublicationService(config, fetcher)
    _, workflow, _, bundle = service.draft(task['id'])
    source = fresh_input(fetcher, task['business_date'], ANALYSIS_ASOF)
    baseline = freeze_baseline(source, workflow['manifest'], ANALYSIS_ASOF)
    from foot_web.services.recommendations import build_bundle
    empty = build_bundle(source, [], workflow['manifest'], ANALYSIS_ASOF)
    assert empty['groups'] == []
    assert baseline['tickets'] and baseline['reference_only']
    for ticket in baseline['tickets']:
        assert ticket['model_probability'] is ticket['EV'] is ticket['actual_stake'] is None
        assert all(float(n) > 2.5 for n in ticket['effective_multiples'])
        assert all(float(o['odds']) >= 1.33 for leg in ticket['legs'] if leg['sport'] == 'football' for o in leg['options'])
    # Selling and strict pre-kickoff are retained, even without the evidence gate.
    stopped = copy.deepcopy(source)
    for sport in ('football', 'basketball'):
        for match in stopped[sport]:
            match['status'] = 'Closed'
    assert freeze_baseline(stopped, workflow['manifest'], ANALYSIS_ASOF)['tickets'] == []


@pytest.mark.parametrize('change', ['content', 'binding', 'source', 'future', 'schema', 'provider', 'manifest', 'probability'])
def test_invalid_frozen_baseline_is_gap_not_recalculation(researched, change):
    config, _, task, fetcher = researched
    service = PublicationService(config, fetcher)
    checked = service.check(task['id'], 'admin1', now=ANALYSIS_ASOF)
    publication, _ = service.publish(task['id'], checked['id'], 'admin1', confirmed=True, now=ANALYSIS_ASOF)
    folder = Path(publication['folder'])
    baseline = json.loads((folder / 'baseline.json').read_text())
    audit = json.loads((folder / 'audit.json').read_text())
    if change == 'binding':
        publication['baseline_sha256'] = 'wrong'
    elif change == 'source':
        audit['source_sha256'] = 'wrong'
    elif change == 'future':
        audit['source']['as_of'] = '2099-01-01T00:00:00+08:00'
    elif change == 'content':
        baseline['tickets'][0]['p_mkt'] = .1
    else:
        if change == 'schema':
            baseline['schema_sha256'] = 'wrong'
        elif change == 'provider':
            baseline['runtime_provider'] = 'harness'
        elif change == 'manifest':
            baseline['manifest']['code_sha256'] = 'wrong'
        elif change == 'probability':
            baseline['tickets'][0]['p_mkt'] = None
        baseline['content_sha256'] = fingerprint({k: v for k, v in baseline.items() if k != 'content_sha256'})
        publication['baseline_sha256'] = baseline['content_sha256']
    with pytest.raises((ValueError, KeyError)):
        validate_baseline(baseline, publication, audit)
    (folder / 'baseline.json').write_text(json.dumps(baseline))
    (folder / 'audit.json').write_text(json.dumps(audit))
    with service.store.store.connect() as db:
        db.execute('UPDATE publications SET payload=? WHERE id=?', (json.dumps(publication), publication['id']))
    report = Evaluation(config, None, service.store).paired_comparison()
    assert report['gaps'] and report['baseline_available'] == 0
