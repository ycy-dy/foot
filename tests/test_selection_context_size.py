"""Score breakdown is retained once, not repeated for every price alternative."""
from foot_web.services import selection


def test_candidate_context_deduplicates_evidence_scores(monkeypatch):
    score = {'version': 'evidence-policy-1.0.0', 'eligible': True,
             'evidence_confidence': 70, 'breakdown': {'1': {'weight': 12}},
             'reasons': ['reason']}
    option = {'option_id': 'option-1', 'match_key': 'match-1', 'sport': 'football',
              'num': '周日001', 'home': 'home', 'away': 'away', 'kickoff': '2026-11-08 13:00',
              'period': 'early', 'market': 'HAD', 'L': '', 'label': '主胜',
              'options': [{'key': 'h', 'label': '主胜', 'odds': '1.50'}],
              'p_mkt': .6, 'evidence_confidence': score}

    def build(source, items, manifest, as_of, catalog):
        catalog['single:match-1'] = [option]
        return {'matches': [{'num': '周日001', 'exclusion': None}]}

    monkeypatch.setattr(selection, 'build_bundle', build)
    context = selection.decision_context({'business_date': '2026-11-08'}, [], {}, None)
    assert context['options']['option-1']['evidence_confidence'] == {
        'version': score['version'], 'eligible': True, 'evidence_confidence': 70}
