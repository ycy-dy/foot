import json, subprocess, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent
out = {}
for sport, v in [('football', 1), ('basketball', 2)]:
    rows = []
    page = 1
    while True:
        url = f'https://webapi.sporttery.cn/gateway/uniform/{sport}/getUniformMatchResultV{v}.qry?matchBeginDate=2026-09-01&matchEndDate=2026-11-04&leagueId=&pageSize=100&pageNo={page}&isFix=0&matchPage=1&pcOrWap=1'
        d = json.loads(subprocess.run(['curl', '-sS', '--max-time', '30', url], capture_output=True, text=True).stdout)
        val = d['value']; rows += val['matchResult']
        if page >= val['pages']: break
        page += 1; time.sleep(0.3)
    out[sport] = rows
    print(sport, len(rows), rows[-1]['matchDate'], list(rows[0].keys()))
(ROOT / 'official_results_2026-09-01_to_11-04.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
