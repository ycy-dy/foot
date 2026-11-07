import copy
import json
from pathlib import Path
import pytest
from foot_web.data.markets import parse_football, parse_basketball
from foot_web.services.research import match_key

FIX = Path(__file__).parent / 'fixtures'


@pytest.mark.parametrize('sport,parser', [('football', parse_football), ('basketball', parse_basketball)])
def test_missing_official_id_is_none_not_weekday_number(sport, parser):
    data = json.loads((FIX / (sport + '_2026-11-04.json')).read_text())
    for group in data['value']['matchInfoList']:
        for match in group['subMatchList']:
            for key in ('matchId', 'matchIdStr', 'matchID', 'id'):
                match.pop(key, None)
    assert all(row['official_id'] is None for row in parser(data))


def test_official_id_does_not_bypass_snapshot_identity_binding():
    match = {'sport':'football','official_id':'id1','business_date':'2026-11-07',
             'num':'周六001','home':'甲','away':'乙','kickoff':'2026-11-07 18:00'}
    for field, changed in [('business_date','2026-11-08'),('home','丙'),('away','丁'),('kickoff','2026-11-07 20:00')]:
        assert match_key(match) != match_key(match | {field: changed})
    assert match_key(match) == match_key(copy.deepcopy(match))
