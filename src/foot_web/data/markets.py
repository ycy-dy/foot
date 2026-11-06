"""官方竞彩计算器数据 → 展示用赛程（含比例去水 p_mkt）。口径与 V6 第20节、analysis_2026-11-04_hitrate/analyze.py 一致。"""
from datetime import datetime, timedelta
from decimal import Decimal
from math import isfinite

HAFU_LBL = {'hh': '胜胜', 'hd': '胜平', 'ha': '胜负', 'dh': '平胜', 'dd': '平平', 'da': '平负', 'ah': '负胜', 'ad': '负平', 'aa': '负负'}
PERIOD_FB = {'early': '早场', 'middle': '中场', 'late': '晚场', 'outside': '窗口外'}
PERIOD_BK = {'early': '早场', 'late': '晚场'}
WEEK = '一二三四五六日'


def devig(prices):
    try:
        vals = {k: float(v) for k, v in prices.items()}
    except (TypeError, ValueError):
        return None
    if not vals or any(not isfinite(v) or v <= 0 for v in vals.values()):
        return None
    inv = {k: 1 / v for k, v in vals.items()}
    q = sum(inv.values())
    return {k: inv[k] / q for k in inv}


def pool_state(m, code):
    for p in m.get('poolList') or []:
        if p.get('poolCode') == code:
            return {'selling': p.get('poolStatus') == 'Selling', 'allup': p.get('bettingAllup') == 1, 'single': p.get('bettingSingle') == 1}
    return {'selling': False, 'allup': False, 'single': False}


def market(m, src_key, code, keys):
    src = m.get(src_key) or {}
    prices = {k: src.get(k) or None for k in keys}
    p = devig(prices) if all(prices.values()) else None
    return {'prices': prices, 'p': p, 'line': src.get('goalLine') or '', 'update': f"{src.get('updateDate', '')} {src.get('updateTime', '')}".strip(),
            **pool_state(m, code)}


def football_period(bd, ko):
    d = datetime.fromisoformat(bd)
    if not (d.replace(hour=12) <= ko <= (d + timedelta(days=1)).replace(hour=9)):
        return 'outside'
    if ko <= d.replace(hour=19, minute=30):
        return 'early'
    return 'middle' if ko < d.replace(hour=23) else 'late'


def parse_football(data):
    out = []
    for g in (data.get('value') or {}).get('matchInfoList') or []:
        for m in g.get('subMatchList') or []:
            bd = m['businessDate']
            ko = datetime.fromisoformat(f"{m['matchDate']} {m['matchTime']}")
            had = market(m, 'had', 'HAD', 'hda')
            hhad = market(m, 'hhad', 'HHAD', 'hda')
            ttg = market(m, 'ttg', 'TTG', [f's{i}' for i in range(8)])
            hafu = market(m, 'hafu', 'HAFU', list(HAFU_LBL))
            crs_src = m.get('crs') or {}
            crs_keys = [k for k in crs_src if k.startswith('s') and not k.endswith('f') and crs_src.get(k)]
            crs = {'prices': {k: crs_src[k] for k in crs_keys}, 'p': devig({k: crs_src[k] for k in crs_keys}), **pool_state(m, 'CRS')}
            L = hhad['line']
            dd_p = had['p']['d'] + hhad['p']['d'] if had['p'] and hhad['p'] and L not in ('', '0', '+0') else None
            best_ttg = None
            if ttg['p']:
                i = max(range(7), key=lambda j: ttg['p'][f's{j}'] + ttg['p'][f's{j + 1}'])
                best_ttg = {'pair': (i, i + 1), 'odds': (ttg['prices'][f's{i}'], ttg['prices'][f's{i + 1}']), 'p': ttg['p'][f's{i}'] + ttg['p'][f's{i + 1}']}
            top_crs = None
            if crs['p']:
                k = max((k for k in crs['p'] if k[1:3].isdigit()), key=lambda k: crs['p'][k], default=None)
                if k:
                    top_crs = {'score': f'{int(k[1:3])}:{int(k[4:6])}', 'odds': crs['prices'][k], 'p': crs['p'][k]}
            trigger = None
            if hhad['prices']['h'] and hhad['prices']['a'] and L:
                Ld = Decimal(L)
                if Ld < 0 and Decimal(hhad['prices']['h']) < Decimal(hhad['prices']['a']):
                    trigger = 'hh'
                elif Ld > 0 and Decimal(hhad['prices']['a']) < Decimal(hhad['prices']['h']):
                    trigger = 'aa'
            out.append({'sport': 'football', 'num': m['matchNumStr'], 'business_date': bd, 'kickoff': ko.isoformat(sep=' ', timespec='minutes'),
                        'period': football_period(bd, ko), 'league': m.get('leagueAbbName', ''), 'home': m.get('homeTeamAllName', ''),
                        'away': m.get('awayTeamAllName', ''), 'status': m.get('matchStatus', ''), 'L': L,
                        'had': had, 'hhad': hhad, 'ttg': ttg, 'hafu': hafu, 'crs': crs, 'dd_p': dd_p, 'best_ttg': best_ttg,
                        'top_crs': top_crs, 'half_full_trigger': trigger})
    return sorted(out, key=lambda r: (r['business_date'], r['kickoff'], r['num']))


def parse_basketball(data):
    out = []
    for g in (data.get('value') or {}).get('matchInfoList') or []:
        for m in g.get('subMatchList') or []:
            bd = m['businessDate']
            ko = datetime.fromisoformat(f"{m['matchDate']} {m['matchTime']}")
            d = datetime.fromisoformat(bd)
            out.append({'sport': 'basketball', 'num': m['matchNumStr'], 'business_date': bd, 'kickoff': ko.isoformat(sep=' ', timespec='minutes'),
                        'period': 'early' if ko < d.replace(hour=23) else 'late', 'league': m.get('leagueAbbName', ''),
                        'away': m.get('awayTeamAllName', ''), 'home': m.get('homeTeamAllName', ''), 'status': m.get('matchStatus', ''),
                        'mnl': market(m, 'mnl', 'MNL', 'ha'), 'hdc': market(m, 'hdc', 'HDC', 'ha'), 'hilo': market(m, 'hilo', 'HILO', 'hl')})
    return sorted(out, key=lambda r: (r['business_date'], r['kickoff'], r['num']))


def business_dates(rows):
    return sorted({r['business_date'] for r in rows})


def weekday_label(bd):
    return '周' + WEEK[datetime.fromisoformat(bd).weekday()]
