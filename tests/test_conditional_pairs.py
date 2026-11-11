"""User-authorized conditional pairs never fabricate a score or physical fixture."""
import copy

from conftest import ANALYSIS_ASOF, FakeFetcher, decision_response, research_payload
from foot_web.engine.tasks import prepare_input
from foot_web.services.recommendations import build_bundle
from foot_web.services.research import match_key
from foot_web.services.selection import decision_context, make_decision_prompt, apply_decision
from foot_web.services.versions import rules_manifest


def case(cfg):
    source = prepare_input(cfg, {'business_date': '2026-11-04'}, FakeFetcher(), ANALYSIS_ASOF)
    source['football'], source['basketball'] = source['football'][:2], []
    items = [{'match_key': match_key(m), 'match': m, 'status': 'succeeded', 'payload': research_payload(m)}
             for m in source['football']]
    return source, items, rules_manifest(cfg['PROJECT_DIR'])[0]


def test_zero_qualified_matches_still_require_an_explicit_conditional_pair(cfg):
    source, items, manifest = case(cfg)
    context = decision_context(source, items, manifest, ANALYSIS_ASOF)
    result = decision_response(make_decision_prompt(context))
    bundle = apply_decision(result, context, source, items, manifest, ANALYSIS_ASOF,
                            {'provider': 'codex', 'validated_sha256': 'offline'})
    assert len(bundle['groups']) == 1
    group = bundle['groups'][0]
    assert group['recommendation_status'] == 'conditional_low_confidence'
    assert all(leg['evidence_confidence']['eligible'] is False for leg in group['legs'])
    assert all(leg['model_probability'] is None and leg['EV'] is None for leg in group['legs'])
    assert not bundle['dream_legs'] and not any(row['leg'] for row in bundle['six'])


def test_started_or_unsaleable_matches_cannot_be_invented_for_a_daily_pair(cfg):
    source, items, manifest = case(cfg)
    source['football'][0]['status'] = 'Closed'
    bundle = build_bundle(source, items, manifest, ANALYSIS_ASOF)
    assert not bundle['groups']
    assert '70' not in bundle['periods'][0]['reason']


def test_confirmed_conflict_is_not_a_quality_gap_fallback(cfg):
    source, items, manifest = case(cfg)
    items[0]['payload']['dimensions'][20]['status'] = 'conflict'
    assert not build_bundle(source, items, manifest, ANALYSIS_ASOF)['groups']
