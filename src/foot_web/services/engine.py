"""实时候选引擎（V6 第20节的确定性部分）：选项枚举 → 八结构 → 整单实际倍数>2.5 → 联合 p_mkt 排序。

不含非赔率证据（伤停/首发等）与推荐理由；这些由后台 Claude/Codex 生成草稿，审核发布另行处理。
本模块结果在界面上标记为“市场候选排序”，不得称为最终推荐（V6 20.8：赔率/排序本身不算理由）。
"""
import itertools
from decimal import Decimal

from ..data.markets import HAFU_LBL
from .audit import GATE, MIN_FB, structure_ok

STRUCT_NAME = {('DD', 'HAD'): '①胜平负＋双平', ('HAD', 'TTG'): '②胜平负＋进球数', ('HHAD', 'TTG'): '③让球＋进球数',
               ('DD', 'HHAD'): '④让球＋双平', ('DD', 'HAFU'): '⑤半全场＋双平', ('HAFU', 'TTG'): '⑥半全场＋进球数',
               ('HAD', 'HAD'): '⑦胜平负＋胜平负', ('HAFU', 'HAFU'): '⑧半全场＋半全场'}
STRUCT_ORDER = list(STRUCT_NAME.values())
CATEGORY = {'HAD': '胜平负', 'HHAD': '让球', 'TTG': '进球数', 'DD': '双平', 'HAFU': '半全场'}
LBL_HAD = {'h': '主胜', 'd': '平', 'a': '客胜'}
LBL_HH = {'h': '让胜', 'd': '让平', 'a': '让负'}


def struct_name(c1, c2):
    return STRUCT_NAME.get(tuple(sorted((c1, c2))))


def _goal_name(i):
    return '7+球' if i == 7 else f'{i}球'


def football_options(m):
    """一场比赛所有合规选项（在售、可过关、每个实际选项≥1.33）。"""
    out = []

    def add(code, label, branches, p, key_opts):
        if p is None or any(Decimal(o) < MIN_FB for _, o in branches):
            return
        out.append({'code': code, 'category': CATEGORY[code], 'label': label, 'p': p,
                    'branches': [{'label': l, 'odds': o} for l, o in branches],
                    'audit_options': [{'key': k, 'label': l, 'odds': o} for k, l, o in key_opts]})
    had, hh, ttg, hafu, L = m['had'], m['hhad'], m['ttg'], m['hafu'], m['L']
    if had['p'] and had['selling'] and had['allup']:
        for k in 'hda':
            add('HAD', LBL_HAD[k], [(LBL_HAD[k], had['prices'][k])], had['p'][k], [(k, LBL_HAD[k], had['prices'][k])])
    if hh['p'] and hh['selling'] and hh['allup']:
        for k in 'hda':
            add('HHAD', f'（主{L}）{LBL_HH[k]}', [(LBL_HH[k], hh['prices'][k])], hh['p'][k], [(k, LBL_HH[k], hh['prices'][k])])
    if ttg['p'] and ttg['selling'] and ttg['allup']:
        for i in range(7):
            a, b = f's{i}', f's{i + 1}'
            add('TTG', f'{_goal_name(i)}／{_goal_name(i + 1)}', [(_goal_name(i), ttg['prices'][a]), (_goal_name(i + 1), ttg['prices'][b])],
                ttg['p'][a] + ttg['p'][b], [(a, _goal_name(i), ttg['prices'][a]), (b, _goal_name(i + 1), ttg['prices'][b])])
    if m['dd_p'] is not None and had['allup'] and hh['allup'] and had['selling'] and hh['selling']:
        add('DD', f'（主{L}）平／让平', [('平', had['prices']['d']), ('让平', hh['prices']['d'])], m['dd_p'],
            [('had_d', '平', had['prices']['d']), ('hhad_d', '让平', hh['prices']['d'])])
    if hafu['p'] and hafu['selling'] and hafu['allup']:
        for k, lab in HAFU_LBL.items():
            add('HAFU', lab, [(lab, hafu['prices'][k])], hafu['p'][k], [(k, lab, hafu['prices'][k])])
    return sorted(out, key=lambda o: -o['p'])


def basketball_options(m):
    out = []
    for code, keys, lab in (('MNL', 'ah', {'h': '主胜', 'a': '客胜'}), ('HDC', 'ha', {'h': '让胜', 'a': '让负'}), ('HILO', 'hl', {'h': '大分', 'l': '小分'})):
        mk = m[code.lower()]
        if not (mk['p'] and mk['selling'] and mk['allup']):
            continue
        for k in keys:
            name = {'MNL': lab[k] + '（胜负栏）', 'HDC': f"（主{mk['line']}）{lab[k]}", 'HILO': f"{lab[k]}（{mk['line']}）"}[code]
            out.append({'code': code, 'label': name, 'p': mk['p'][k], 'branches': [{'label': name, 'odds': mk['prices'][k]}],
                        'audit_options': [{'key': k, 'label': name, 'odds': mk['prices'][k]}]})
    return sorted(out, key=lambda o: -o['p'])


def _leg(m, o):
    return {'num': m['num'], 'home': m['home'], 'away': m['away'], 'kickoff': m['kickoff'], 'period': m['period'], 'opt': o}


def pairs(matches, opt_fn, sport):
    """两场不同比赛的全部组合，附结构、分支、整单实际倍数与门槛判定。"""
    opts = [(m, opt_fn(m)) for m in matches]
    out = []
    for (m1, o1s), (m2, o2s) in itertools.combinations(opts, 2):
        for o1 in o1s:
            for o2 in o2s:
                st = struct_name(o1['code'], o2['code']) if sport == 'football' else '二串一'
                if sport == 'football' and (not st or not structure_ok(o1['code'], o2['code'])):
                    continue
                prods = [Decimal(a['odds']) * Decimal(b['odds']) for a in o1['branches'] for b in o2['branches']]
                nb = len(prods)
                eff = [x / nb for x in prods]
                out.append({'struct': st, 'legs': [_leg(m1, o1), _leg(m2, o2)], 'p': o1['p'] * o2['p'], 'branches': nb,
                            'prods': [str(x) for x in prods], 'eff': [str(x.quantize(Decimal('0.0001'))) for x in eff],
                            'eff_min': min(eff), 'gate_ok': all(x > GATE for x in eff)})
    out.sort(key=lambda c: -c['p'])
    return out


def available(rows):
    return [r for r in rows if r['status'] == 'Selling']


def football_pools(rows):
    """V6 20.9：中场≥2独立；中场<2且早+中≥2合并为早中场①；晚场②独立。"""
    win = [r for r in available(rows) if r['period'] != 'outside']
    early = [r for r in win if r['period'] == 'early']
    mid = [r for r in win if r['period'] == 'middle']
    late = [r for r in win if r['period'] == 'late']
    if len(mid) >= 2:
        first = ('中场①', mid, f'中场{len(mid)}场')
    else:
        first = ('早中场①', early + mid, f'合并：早场{len(early)}场＋中场{len(mid)}场')
    return [first, ('晚场②', late, f'晚场{len(late)}场')]


def analyze(fb_rows, bk_rows, top=5):
    res = {'football': [], 'basketball': [], 'structures': [], 'six': [], 'dream': None}
    for name, pool, note in football_pools(fb_rows):
        allc = pairs(pool, football_options, 'football') if len(pool) >= 2 else []
        ok = [c for c in allc if c['gate_ok']]
        res['football'].append({'name': name, 'note': note, 'n': len(pool), 'candidates': ok[:top],
                                'reason': None if ok else ('不足两场，不能成串' if len(pool) < 2 else '没有整单实际倍数>2.5的合规组合')})
        best = {}
        for c in ok:
            best.setdefault(c['struct'], c)
        res['structures'].append({'name': name, 'rows': [{'struct': s, 'best': best.get(s)} for s in STRUCT_ORDER]})
    bk = available(bk_rows)
    for key, label in (('early', '早场'), ('late', '晚场')):
        pool = [r for r in bk if r['period'] == key]
        ok = [c for c in pairs(pool, basketball_options, 'basketball') if c['gate_ok']] if len(pool) >= 2 else []
        singles = [] if len(pool) >= 2 else [(_leg(m, basketball_options(m)[0])) for m in pool if basketball_options(m)]
        res['basketball'].append({'name': f'篮球{label}', 'n': len(pool), 'candidates': ok[:top], 'singles': singles,
                                  'reason': None if ok else ('不足两场，不能成串' if len(pool) < 2 else '没有组合赔率>2.5的组合')})
    win = [r for r in available(fb_rows) if r['period'] != 'outside']
    cats = [('胜平负', lambda o: o['code'] == 'HAD'), ('让球', lambda o: o['code'] == 'HHAD'), ('进球数', lambda o: o['code'] == 'TTG'),
            ('二三球', lambda o: o['code'] == 'TTG' and o['label'] == '2球／3球'), ('半全场', lambda o: o['code'] == 'HAFU'),
            ('双平', lambda o: o['code'] == 'DD')]
    for cat, f in cats:
        cand = [_leg(m, o) for m in win for o in football_options(m) if f(o)]
        cand.sort(key=lambda l: -l['opt']['p'])
        res['six'].append({'category': cat, 'best': cand[0] if cand else None, 'alts': cand[1:3]})
    tops = []
    for m in win:
        c = m['crs']
        if not (c['p'] and c['selling'] and c['allup']):
            continue
        k = max((k for k in c['p'] if k[1:3].isdigit()), key=lambda k: c['p'][k], default=None)
        if k:
            tops.append({'num': m['num'], 'home': m['home'], 'away': m['away'], 'score': f'{int(k[1:3])}:{int(k[4:6])}', 'odds': c['prices'][k], 'p': c['p'][k]})
    tops.sort(key=lambda d: -d['p'])
    if len(tops) >= 4:
        legs = tops[:4]
        prod = Decimal(1)
        pj = 1.0
        for d in legs:
            prod *= Decimal(d['odds']); pj *= d['p']
        res['dream'] = {'legs': legs, 'product': str(prod.quantize(Decimal('0.01'))), 'p': pj}
    return res
