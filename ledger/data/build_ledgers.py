"""Settle all normalized recommendation records against official results and write two ledgers."""
import csv, itertools, json, re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
RES = json.loads((HERE / 'official_results_2026-09-01_to_11-04.json').read_text())
IDX = defaultdict(list)
for sport, rows in RES.items():
    for r in rows:
        IDX[sport, r['matchNumStr']].append(r)
records = []
for f in sorted(HERE.glob('*records*.jsonl')):
    records += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
NOW = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
def q2(x): return str(Decimal(x).quantize(Decimal('0.01'), ROUND_HALF_UP))
def wdl(a, b): return 'h' if a > b else 'a' if a < b else 'd'
CRS_STD = {'h': {(1,0),(2,0),(2,1),(3,0),(3,1),(3,2),(4,0),(4,1),(4,2),(5,0),(5,1),(5,2)}, 'd': {(0,0),(1,1),(2,2),(3,3)}}

def find(leg, bdate):
    d0 = date.fromisoformat(bdate)
    cands = [r for r in IDX[leg['sport'], leg['number']] if 0 <= (date.fromisoformat(r['matchDate']) - d0).days <= 2]
    return min(cands, key=lambda r: r['matchDate']) if cands else None

def result_of(leg, bdate):
    r = find(leg, bdate)
    if r is None:
        return None, '未找到官方赛果'
    if leg['sport'] == 'football':
        full, half = r.get('sectionsNo999') or '', r.get('sectionsNo1') or ''
        if ':' not in full or str(r.get('matchResultStatus')) != '2':
            return None, f"官方状态{r.get('matchResultStatus')}/{r.get('resultStatus') or ''}，待定或取消"
        H, A = map(int, full.split(':'))
        hh, ha = map(int, half.split(':')) if ':' in half else (None, None)
        return {'H': H, 'A': A, 'hH': hh, 'hA': ha, 'score': full, 'half': half, 'official_name': f"{r['allHomeTeam']} VS {r['allAwayTeam']}"}, ''
    fs = r.get('finalScore') or ''
    if '-' not in fs:
        return None, '篮球待定或取消'
    A, H = map(int, fs.split('-'))
    return {'H': H, 'A': A, 'score': f'{A}:{H}', 'half': '', 'official_name': f"{r['allAwayTeam']}（客） VS {r['allHomeTeam']}（主）"}, ''

def option_hit(leg, opt, x):
    m, k, H, A = leg['market'], opt['key'], x['H'], x['A']
    L = Decimal(leg['goal_line'] or 0)
    if m in ('HAD', 'MNL'): return k == wdl(H, A)
    if m in ('HHAD', 'HDC'): return k == wdl(Decimal(H) + L, Decimal(A))
    if m == '双平':
        handicap = k == 'hhad_d' or (k not in ('had_d',) and '让' in opt['label'])
        return (Decimal(H) + L == A) if handicap else H == A
    if m == 'TTG': return k == f's{min(H + A, 7)}'
    if m == 'HAFU':
        if x.get('hH') is None: return None
        return k == wdl(x['hH'], x['hA']) + wdl(H, A)
    if m == 'HILO': return k == ('h' if H + A > L else 'l')
    if m == 'CRS':
        mm = re.fullmatch(r's(\d+)s(\d+)', k)
        if mm: return (H, A) == (int(mm[1]), int(mm[2]))
        o = {'s1sh': 'h', 's1sd': 'd', 's1sa': 'a'}.get(k)
        if o is None: return None
        w = wdl(H, A)
        std = CRS_STD['h'] if w == 'h' else CRS_STD['d'] if w == 'd' else {(b, a) for a, b in CRS_STD['h']}
        return w == o and (H, A) not in std
    return None

def settle(rec):
    legs, pending = [], False
    for leg in rec['legs']:
        x, note = result_of(leg, rec['business_date'])
        if x is None or leg['market'] == 'UNKNOWN':
            pending = True
            legs.append(leg | {'score': None, 'half': None, 'hits': [None] * len(leg['options']), 'hit': None, 'note': note or '玩法无法映射'})
            continue
        hits = [option_hit(leg, o, x) for o in leg['options']]
        legs.append(leg | {'score': x['score'], 'half': x['half'], 'hits': hits, 'hit': None if None in hits and not any(hits) else any(h for h in hits if h), 'note': ''})
    branches = []
    for combo in itertools.product(*[range(len(l['options'])) for l in legs]):
        odds = [legs[i]['options'][j]['odds'] for i, j in enumerate(combo)]
        hs = [legs[i]['hits'][j] for i, j in enumerate(combo)]
        prod = None if None in odds else Decimal(1)
        if prod is not None:
            for o in odds: prod *= Decimal(o)
        branches.append({'product': None if prod is None else str(prod.normalize()), 'hit': None if None in hs else all(hs)})
    hit = None if any(l['hit'] is None for l in legs) else any(b['hit'] for b in branches)
    cost = 2 * len(branches)
    ret = None
    if hit is not None and all(b['product'] for b in branches):
        ret = sum((Decimal(b['product']) * 2 for b in branches if b['hit']), Decimal(0))
    return rec | {'settled_legs': legs, 'branches': branches, 'hit': hit, 'legs_hit': sum(l['hit'] is True for l in legs), 'legs_total': len(legs),
                  'sim_cost': cost, 'theoretical_return': None if ret is None else q2(ret), 'actual_stake': None, 'actual_return': None}

S = [settle(r) for r in records]
S.sort(key=lambda r: (r['business_date'], r['ledger'], r['kind'], r.get('superseded') is True))
(HERE / 'settled_records.json').write_text(json.dumps(S, ensure_ascii=False, indent=1))

def legtxt(l):
    gl = f"（主{l['goal_line']}）" if l['market'] in ('HHAD', '双平', 'HDC') and l['goal_line'] else ''
    if l['market'] == 'HILO': gl = f"（总分{l['goal_line']}）"
    return f"（场次 {l['number']}）{l['matchup']} {gl}" + '／'.join(f"{o['label']}（赔率@{o['odds'] or 'null'}）" for o in l['options'])
def status(r):
    if r.get('superseded') is True: return '已被替代，不计分母'
    return '待定' if r['hit'] is None else '命中' if r['hit'] else '未中'
def scoretxt(r): return '；'.join(f"{l['number']} {l['score'] or '—'}" + (f"（半{l['half']}）" if l.get('half') else '') for l in r['settled_legs'])
def rate(h, n): return f"{h}/{n}（{Decimal(h * 100) / n:.2f}%）" if n else '0/0（—）'

def summary_table(rows, keyf, title):
    agg = defaultdict(lambda: [0, 0, Decimal(0), Decimal(0), 0])
    for r in rows:
        if r.get('superseded') is True or r['hit'] is None: continue
        for k in (keyf(r), '合计'):
            a = agg[k]; a[0] += r['hit']; a[1] += 1
            if r['theoretical_return'] is not None:
                a[2] += r['sim_cost']; a[3] += Decimal(r['theoretical_return']); a[4] += 1
    out = [f'| {title} | 命中/已结算 | 命中率 | 模拟成本 | 理论返还 | 理论回报率 |', '| --- | --- | --- | --- | --- | --- |']
    for k in sorted(agg, key=lambda k: (k == '合计', k)):
        h, n, c, ret, _ = agg[k]
        roi = f"{(ret - c) * 100 / c:.2f}%" if c else '—'
        out.append(f'| {k} | {h}/{n} | {Decimal(h * 100) / n:.2f}% | {c} | {q2(ret)} | {roi} |')
    return '\n'.join(out)

HDR = f"最后生成：{NOW}。赛果来自竞彩官方结果接口（足球主:客；篮球客:主），按原发布盘口/赔率结算，不用收盘盘口改写原票。模拟成本按每分支2元计算，理论返还未扣税费，仅为数学示例；实际投注金额、实际返还全部null（未获真实投注授权）。已被替代的旧版本保留展示但不计入分母。未提交、未下单。\n"
# ---- six ledger
six = [r for r in S if r['ledger'] == 'six']
L = ['# 六类方向台账\n', HDR, '## 一、按类别汇总\n', summary_table(six, lambda r: r['kind'], '类别'), '\n## 二、按业务日汇总\n', summary_table(six, lambda r: r['business_date'], '业务日'),
     '\n## 三、逐条明细\n', '| 业务日 | 类别 | 具体方向 | 赛果（半场） | 状态 | 模拟成本 | 理论返还 | 实际投入/返还 | 依据摘要 | 来源 |', '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
for r in six:
    L.append(f"| {r['business_date']} | {r['kind']} | {legtxt(r['legs'][0])} | {scoretxt(r)} | {status(r)} | {r['sim_cost']} | {r['theoretical_return'] or 'null'} | null/null | {(r.get('reason') or '').replace('|', '／')[:80]} | {r['source_file']} |")
(BASE / 'ledger_six_directions.md').write_text('\n'.join(L) + '\n')
# ---- recommendation ledger
rec = [r for r in S if r['ledger'] == 'rec']
L = ['# 推荐台账（最终串／单场方向／梦想单）\n', HDR, '## 一、按栏目汇总\n', summary_table(rec, lambda r: r['kind'], '栏目'),
     '\n## 二、最终串单腿命中\n']
legagg = defaultdict(lambda: [0, 0])
for r in rec:
    if r.get('superseded') is True or r['kind'] not in ('足球最终串', '篮球最终串'): continue
    for l in r['settled_legs']:
        if l['hit'] is None: continue
        for k in (r['kind'], '合计'):
            legagg[k][0] += l['hit']; legagg[k][1] += 1
L += ['| 栏目 | 单腿命中/已结算 |', '| --- | --- |'] + [f'| {k} | {rate(*v)} |' for k, v in sorted(legagg.items(), key=lambda kv: kv[0] == '合计')]
L += ['\n## 三、按业务日汇总\n', summary_table(rec, lambda r: r['business_date'], '业务日'),
      '\n## 四、逐票明细\n', '| 业务日 | 栏目 | 标题/等级 | 原票（逐项赔率） | 分支组合赔率 | 赛果（半场） | 腿命中 | 状态 | 模拟成本 | 理论返还 | 实际投入/返还 | 来源 |', '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
for r in rec:
    prods = '／'.join(b['product'] or 'null' for b in r['branches'])
    L.append(f"| {r['business_date']} | {r['kind']} | {r['title']}／{r.get('status_label') or ''} | {'＋'.join(legtxt(l) for l in r['legs'])} | {prods} | {scoretxt(r)} | {r['legs_hit']}/{r['legs_total']} | {status(r)} | {r['sim_cost']} | {r['theoretical_return'] or 'null'} | null/null | {r['source_file']} |")
(BASE / 'ledger_recommendations.md').write_text('\n'.join(L) + '\n')
for name, rows in [('ledger_six_directions.csv', six), ('ledger_recommendations.csv', rec)]:
    with open(BASE / name, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['业务日', '台账', '栏目/类别', '标题', '原票', '分支组合赔率', '赛果', '腿命中', '状态', '模拟成本', '理论返还', '实际投入', '实际返还', '是否被替代', '来源'])
        for r in rows:
            w.writerow([r['business_date'], r['ledger'], r['kind'], r['title'], '＋'.join(legtxt(l) for l in r['legs']), '／'.join(b['product'] or 'null' for b in r['branches']), scoretxt(r), f"{r['legs_hit']}/{r['legs_total']}", status(r), r['sim_cost'], r['theoretical_return'], None, None, r.get('superseded'), r['source_file']])
pend = [(r['business_date'], r['kind'], [l['note'] for l in r['settled_legs'] if l['note']]) for r in S if r['hit'] is None and r.get('superseded') is not True]
print('records', len(S), 'pending/unsettled', pend)
