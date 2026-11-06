import json
from pathlib import Path
BASE = Path(__file__).resolve().parents[2] / 'history' / 'daily'   # 2026-11-04目录重构后历史目录位置
SRC = [
 ('2026-10-30', 'review_2026-10-29_and_analysis_2026-10-30_1117/recommendations.json', False, None),
 ('2026-11-02', 'review_2026-10-30_and_analysis_2026-11-02/recommendations.json', False, None),
 ('2026-11-03', 'review_2026-11-02_and_analysis_2026-11-03/recommendations.json', True, 'review_2026-11-02_and_analysis_2026-11-03_1540/recommendations.json'),
 ('2026-11-03', 'review_2026-11-02_and_analysis_2026-11-03_1540/recommendations.json', False, None),
 ('2026-11-04', 'review_2026-11-03_and_analysis_2026-11-04/recommendations.json', True, 'history/daily/analysis_2026-11-04_hitrate/report.md'),
]
def nl(l):
    return {k: l.get(k, '') for k in ['sport', 'number', 'matchup', 'market', 'goal_line']} | {'options': [{'key': o['key'], 'label': o['label'], 'odds': o.get('odds')} for o in l['options']]}
out = []
for date, f, sup, by in SRC:
    d = json.loads((BASE / f).read_text())
    base = {'business_date': date, 'source_file': f, 'snapshot': d.get('snapshot'), 'superseded': sup, 'superseded_by': by, 'version_note': '上午版本，被下午版本替代' if sup else ''}
    def add(ledger, kind, obj, title=None, reason=''):
        legs = obj['legs'] if 'legs' in obj else [obj]
        out.append(base | {'ledger': ledger, 'kind': kind, 'title': title or obj.get('title', kind), 'status_label': obj.get('status', '低置信度条件推荐'), 'stars': None,
                           'legs': [nl(l) for l in legs], 'reason': (reason or obj.get('reason', ''))[:200]})
    for k, kind in [('football_final', '足球最终串'), ('football_middle', '足球最终串'), ('basketball_final', '篮球最终串'), ('basketball_early', '篮球最终串'), ('basketball_late', '篮球最终串')]:
        if d.get(k): add('rec', kind, d[k])
    for k, kind, t in [('football_middle_single_direction', '足球单场方向', '足球中场单方向'), ('football_early_observation', '足球单场方向', '足球早场观察方向'), ('basketball_early_direction', '篮球单场方向', '篮球早场单方向'), ('basketball_late_direction', '篮球单场方向', '篮球晚场单方向')]:
        if d.get(k): add('rec', kind, d[k], t)
    if d.get('dream'): add('rec', '梦想单', d['dream'])
    for s in d.get('six_directions', []):
        add('six', s['category'], s['leg'], s['category'], s.get('reason', ''))
(Path(__file__).parent / 'recent_records_1030_1104.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in out) + '\n')
from collections import Counter
print(Counter((r['business_date'], r['ledger'], r['kind'], r['superseded']) for r in out))
