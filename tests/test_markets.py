import json
from datetime import datetime
from pathlib import Path

from foot_web.data import markets
from foot_web.data.fetcher import Fetcher

FIX = Path(__file__).parent / 'fixtures'


def test_devig_sums_to_one():
    p = markets.devig({'h': '1.35', 'd': '4.80', 'a': '5.25'})
    assert abs(sum(p.values()) - 1) < 1e-9 and p['h'] > 0.6
    assert markets.devig({'h': None, 'd': '3'}) is None


def test_football_periods():
    bd = '2026-11-04'
    assert markets.football_period(bd, datetime(2026, 11, 4, 19, 30)) == 'early'
    assert markets.football_period(bd, datetime(2026, 11, 4, 20, 15)) == 'middle'
    assert markets.football_period(bd, datetime(2026, 11, 5, 4, 0)) == 'late'
    assert markets.football_period(bd, datetime(2026, 11, 5, 9, 0)) == 'late'
    assert markets.football_period(bd, datetime(2026, 11, 6, 6, 30)) == 'outside'


def test_parse_football_fixture():
    rows = markets.parse_football(json.loads((FIX / 'football_2026-11-04.json').read_text()))
    m = {r['num']: r for r in rows}['周三005']
    assert m['had']['prices']['a'] == '1.35' and round(m['had']['p']['a'], 3) == 0.65
    assert m['half_full_trigger'] == 'aa'
    assert m['dd_p'] is not None and m['best_ttg']['p'] > 0.3


def test_fetcher_falls_back_to_snapshot(tmp_path):
    class Ok:
        def raise_for_status(self): pass
        def json(self): return json.loads((FIX / 'football_2026-11-04.json').read_text())
    f = Fetcher(tmp_path, http_get=lambda url: Ok())
    _, meta = f.get('football')
    assert not meta['stale'] and Path(meta['file']).exists()

    def boom(url):
        raise OSError('network down')
    f2 = Fetcher(tmp_path, http_get=boom)
    payload, meta2 = f2.get('football')
    assert meta2['stale'] and 'network down' in meta2['error'] and payload['value']
