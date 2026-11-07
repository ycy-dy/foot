from datetime import datetime
from zoneinfo import ZoneInfo

from foot_web.services.evidence_confidence import THRESHOLD, VERSION, passes, score_evidence

ASOF = datetime(2026, 11, 4, 12, tzinfo=ZoneInfo('Asia/Shanghai'))


def evidence(status='verified', *, conflict=False, partial=False):
    source = {'id': 's1', 'url': 'https://official.example/news', 'title': '官方',
              'published_at': '2026-11-03T10:00:00+08:00',
              'effective_at': '2026-11-03T10:00:00+08:00', 'group_id': 'g1', 'tier': 'L1'}
    rows = []
    for i in range(1, 24):
        st = status if i in {1, 4, 7, 9, 12, 13, 15, 17, 18, 19, 21} else 'unknown'
        rows.append({'id': i, 'status': st, 'home': '已核实', 'away': '已核实',
                     'impact': '明确', 'source_ids': ['s1'] if st in {'verified', 'partial', 'conflict'} else []})
    rows[0]['source_ids'] = ['s2'] if status in {'verified', 'partial', 'conflict'} else []
    if conflict:
        rows[3]['status'] = 'conflict'
    if partial:
        rows[12]['status'] = 'partial'
    return {'sources': [source, source | {'id': 's2', 'group_id': 'g2', 'url': 'https://league.example/news'}], 'dimensions': rows,
            'assessments': [{'option_id': 'o1', 'reasons': ['理由一', '理由二'], 'source_ids': ['s1']}],
            'claims': [{'claim_id': 'c1', 'source_id': 's1', 'content_sha256': 'hash', 'quote': '引用', 'locator': 'p1', 'source_type': 'non_odds', 'support_status': 'supports', 'verification_status': 'manual_verified'}]}


def test_verified_contract_reaches_threshold_and_is_policy_not_probability():
    result = score_evidence(evidence(), option_id='o1', as_of=ASOF)
    assert result['version'] == VERSION
    assert result['evidence_confidence'] == 100.0
    assert result['eligible'] and passes(result)
    assert '不是命中概率' in result['policy_note']


def test_partial_is_discounted_and_missing_critical_blocks_compensation():
    result = score_evidence(evidence(partial=True), option_id='o1', as_of=ASOF)
    assert result['breakdown']['13']['factor'] == 0.5
    assert result['evidence_confidence'] >= THRESHOLD
    assert not result['eligible']  # critical partial is an independent hard block


def test_conflict_independently_blocks_even_if_score_would_otherwise_pass():
    result = score_evidence(evidence(conflict=True), option_id='o1', as_of=ASOF)
    assert not result['eligible']
    assert any('冲突' in reason for reason in result['reasons'])


def test_missing_times_or_assessment_returns_ineligible_or_null_contract():
    value = evidence()
    for source in value['sources']:
        source['effective_at'] = None
    result = score_evidence(value, option_id='o1', as_of=ASOF)
    assert result['evidence_confidence'] == 0.0 and not result['eligible']
    assert score_evidence({'dimensions': []}) is None


def test_exact_70_boundary_and_duplicate_groups():
    value = evidence()
    # Remove noncritical weights 1+7+9 = 30. Critical evidence remains verified.
    for i in (1, 7, 9):
        value['dimensions'][i - 1]['status'] = 'unknown'
    value['dimensions'][11]['source_ids'] = ['s2']
    score = score_evidence(value, option_id='o1', as_of=ASOF)
    assert score['evidence_confidence'] == 70 and passes(score)
    value['dimensions'][14]['status'] = 'partial'
    assert not passes(score_evidence(value, option_id='o1', as_of=ASOF))
    value = evidence()
    value['sources'][1]['group_id'] = 'g1'
    assert not passes(score_evidence(value, option_id='o1', as_of=ASOF))


def test_missing_claim_provenance_blocks_new_recommendation():
    value = evidence()
    value['claims'] = [{'claim_id': 'c1', 'source_id': 's1'}]
    result = score_evidence(value, option_id='o1', as_of=ASOF)
    assert not result['eligible'] and any('claim级' in r for r in result['reasons'])


def test_odds_claim_or_unverified_claim_cannot_pass():
    value = evidence()
    value['claims'] = [{'claim_id': 'c1', 'source_id': 's1', 'content_sha256': 'h', 'quote': 'q', 'locator': 'x', 'source_type': 'odds', 'support_status': 'supports', 'verification_status': 'manual_verified'}]
    assert not score_evidence(value, option_id='o1', as_of=ASOF)['eligible']


def test_missing_asof_future_and_stale_sources_fail_closed():
    assert score_evidence(evidence(), option_id='o1') is None
    for stamp in ('2026-11-05T00:00:00+08:00', '2026-09-01T00:00:00+08:00'):
        value = evidence()
        for source in value['sources']:
            source['effective_at'] = source['published_at'] = stamp
        assert not passes(score_evidence(value, option_id='o1', as_of=ASOF))
