import json
from decimal import Decimal
from pathlib import Path

from foot_web.data import markets
from foot_web.services import engine
from foot_web.services.ledger import Ledger

FIX = Path(__file__).parent / 'fixtures'


def day():
    fb = [r for r in markets.parse_football(json.loads((FIX / 'football_2026-11-04.json').read_text())) if r['business_date'] == '2026-11-04']
    bk = [r for r in markets.parse_basketball(json.loads((FIX / 'basketball_2026-11-04.json').read_text())) if r['business_date'] == '2026-11-04']
    return fb, bk


def test_options_respect_min_odds():
    fb, _ = day()
    for m in fb:
        for o in engine.football_options(m):
            assert all(Decimal(b['odds']) >= Decimal('1.33') for b in o['branches'])
    liverpool = {r['num']: r for r in fb}['周三004']
    assert not any(o['code'] == 'HAD' and o['label'] == '客胜' for o in engine.football_options(liverpool))  # 1.31<1.33


def test_analyze_pools_gate_and_ranking():
    fb, bk = day()
    res = engine.analyze(fb, bk)
    em, late = res['football']
    assert em['name'] == '早中场①' and em['n'] == 2 and late['name'] == '晚场②'
    for pool in res['football'] + res['basketball']:
        ps = [c['p'] for c in pool['candidates']]
        assert ps == sorted(ps, reverse=True)
        assert all(c['gate_ok'] and c['eff_min'] > Decimal('2.5') for c in pool['candidates'])
    top = em['candidates'][0]
    assert top['struct'] == '①胜平负＋双平' and {l['num'] for l in top['legs']} == {'周三001', '周三002'}
    assert res['basketball'][0]['reason'] == '不足两场，不能成串' and res['basketball'][0]['singles']
    assert {s['category'] for s in res['six']} == {'胜平负', '让球', '进球数', '二三球', '半全场', '双平'}
    assert res['dream'] and len(res['dream']['legs']) == 4
    assert len(res['structures'][1]['rows']) == 8


def test_ledger_stats_and_filters(tmp_path):
    folder = tmp_path / 'ledger/data'
    folder.mkdir(parents=True)
    rows = [{'business_date': day, 'kind': kind, 'title': kind, 'legs': [],
             'hit': hit, 'superseded': False, 'theoretical_cost': '2',
             'theoretical_return': '4' if hit else '0'}
            for day, kind, hit in [('2026-11-03', '足球最终串', True),
                                   ('2026-11-03', '胜平负', True),
                                   ('2026-11-04', '足球最终串', None)]]
    (folder / 'settled_records.json').write_text(json.dumps(rows))
    lg = Ledger(tmp_path, tmp_path / 'isolated-state')
    assert lg.all()
    cur = lg.query()
    assert all(not r['superseded'] for r in cur)
    st = lg.stats('')
    fr = st['by_group']['最终推荐']
    assert fr['settled'] == fr['hit'] + len([r for r in cur if r['group'] == '最终推荐' and r['state'] == 'miss'])
    assert all(r['state'] == 'pending' for r in lg.query('2026-11-04', '2026-11-04'))
    assert lg.query(state='hit', group='六类方向') and all(r['state'] == 'hit' for r in lg.query(state='hit'))
