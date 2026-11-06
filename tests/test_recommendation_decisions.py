"""Offline contracts for actual AI choices, not post-hoc template explanations."""
import copy

import pytest

from conftest import ANALYSIS_ASOF, FakeFetcher, decision_response, audited_research_payload as research_payload
from foot_web.engine.tasks import prepare_input
from foot_web.services.research import fingerprint, match_key
from foot_web.services.selection import (apply_decision, candidate_id, decision_context, make_decision_prompt,
                                         validate_decision)
from foot_web.services.versions import rules_manifest


@pytest.fixture
def decision_case(cfg):
    source = prepare_input(cfg, {'business_date': '2026-11-04'}, FakeFetcher(), ANALYSIS_ASOF)
    # A small real-fixture early/middle pair keeps validation tests inexpensive.
    source['football'] = source['football'][:2]
    source['basketball'] = []
    items = [{'match_key': match_key(m), 'match': m, 'status': 'succeeded', 'payload': research_payload(m)}
             for m in source['football']]
    manifest, _ = rules_manifest(cfg['PROJECT_DIR'])
    context = decision_context(source, items, manifest, ANALYSIS_ASOF)
    result = decision_response(make_decision_prompt(context))
    return source, items, manifest, context, result


def test_unsourced_legacy_fixture_cannot_become_recommendation(cfg):
    from conftest import research_payload as unsourced_payload
    from foot_web.services.recommendations import all_directions, build_bundle
    source = prepare_input(cfg, {'business_date': '2026-11-04'}, FakeFetcher(), ANALYSIS_ASOF)
    items = [{'match_key': match_key(m), 'match': m, 'status': 'succeeded',
              'payload': unsourced_payload(m)} for m in source['football'] + source['basketball']]
    manifest, _ = rules_manifest(cfg['PROJECT_DIR'])
    context = decision_context(source, items, manifest, ANALYSIS_ASOF)
    assert not context['options']
    bundle = build_bundle(source, items, manifest, ANALYSIS_ASOF)
    assert not all_directions(bundle, include_structures=True)


def validate(case, result=None):
    source, items, manifest, context, original = case
    return validate_decision(result or original, context, source, items, manifest, ANALYSIS_ASOF)


@pytest.mark.parametrize('change', ['identity', 'slot', 'duplicate', 'invented', 'lower_rank', 'reasons', 'source', 'probability', 'empty', 'unsupported_veto'])
def test_invalid_ai_choice_contract_rejected(decision_case, change):
    result = copy.deepcopy(decision_case[-1])
    context = decision_case[3]
    if change == 'identity':
        result['context_sha256'] = 'other-input'
    elif change == 'slot':
        result['choices'].pop()
    elif change == 'duplicate':
        result['choices'].append(copy.deepcopy(result['choices'][0]))
    elif change == 'invented':
        result['choices'][0]['candidate_id'] = 'invented'
    elif change == 'lower_rank':
        row = next(r for r in result['choices'] if r['slot'].startswith('six:') and len(context['slots'][r['slot']]) > 1)
        row['candidate_id'] = context['slots'][row['slot']][-1]['id']
    elif change == 'reasons':
        result['assessments'] = []
    elif change == 'source':
        result['assessments'][0]['source_ids'] = ['invented-source']
    elif change == 'probability':
        result['model_probability'] = .99
    elif change == 'empty':
        result['choices'][0]['candidate_id'] = None
    else:
        result['vetoes'] = [{'option_id': next(iter(context['options'])), 'reason': '无来源的主观降级', 'source_ids': []}]
    with pytest.raises(ValueError):
        validate(decision_case, result)


def test_actual_legs_use_ai_returned_reasons_not_local_generic_templates(decision_case):
    source, items, manifest, context, result = decision_case
    validate(decision_case)
    provenance = {'provider': 'claude', 'validated_sha256': 'verified-response'}
    bundle = apply_decision(result, context, source, items, manifest, ANALYSIS_ASOF, provenance)
    from foot_web.services.recommendations import all_directions
    directions = all_directions(bundle, include_structures=True)
    assert directions and not bundle['reference_only']
    assert all(leg['evidence_confidence']['eligible'] and
               leg['evidence_confidence']['evidence_confidence'] >= 70 for leg in directions)
    assert all(leg['sources'] for leg in directions)
    assert all(leg['reasons'][0].startswith('模拟AI：') and leg['risk'].startswith('模拟AI返回：') for leg in directions)
    assert all(leg['ai_decision_sha256'] == 'verified-response' for leg in directions)


def test_evidence_backed_ai_veto_changes_selected_alternative(decision_case):
    source, items, manifest, _, _ = decision_case
    source_info = {'id': 'official-news', 'url': 'https://example.org/official-news', 'title': '关键组织者缺阵',
                   'published_at': ANALYSIS_ASOF.isoformat(), 'effective_at': ANALYSIS_ASOF.isoformat(),
                   'group_id': 'official-news', 'tier': 'L1'}
    for item in items:
        item['payload']['sources'].append(source_info)
        item['payload']['dimensions'][3].update(
            status='verified', source_ids=['official-news'],
            home='官方确认关键组织者缺阵', away='已核对官方伤停名单')
    context = decision_context(source, items, manifest, ANALYSIS_ASOF)
    original = decision_response(make_decision_prompt(context))
    first = next(row for row in original['choices'] if row['slot'] == 'six:胜平负')
    veto_id = context['slots'][first['slot']][0]['option_ids'][0]
    # This double is an explicit AI choice function over all allowed alternatives.
    # It vetoes a sourced contradiction, rather than explaining the program's first leg.
    from foot_web.services.recommendations import build_bundle
    choices = {}

    def choose(slot, candidates):
        selected = next((candidate for candidate in candidates
                         if all(leg['option_id'] != veto_id for leg in candidate.get('legs', [candidate]))), None)
        choices[slot] = candidate_id(selected) if selected else None
        return selected

    build_bundle(source, items, manifest, ANALYSIS_ASOF, selector=choose)
    original['choices'] = [{'slot': slot, 'candidate_id': key, 'reason': 'AI按有来源反证否决后选择最高剩余基准'}
                           for slot, key in choices.items()]
    original['vetoes'] = [{'option_id': veto_id, 'reason': '官方核心缺阵使本项机制失效', 'source_ids': ['official-news']}]
    original['context_sha256'] = fingerprint(context)
    assert validate_decision(original, context, source, items, manifest, ANALYSIS_ASOF)
    replacement = next(row for row in original['choices'] if row['slot'] == 'six:胜平负')
    assert replacement['candidate_id'] != first['candidate_id']
