"""发布前审核（V6 第20.11节）的库函数版本；tools/audit_recommendations.py 调用本模块。"""
import itertools
from decimal import Decimal

ALLOWED = [{'HAD', 'DD'}, {'HAD', 'TTG'}, {'HHAD', 'TTG'}, {'HHAD', 'DD'}, {'HAFU', 'DD'}, {'HAFU', 'TTG'}]
SAME_ALLOWED = {'HAD', 'HAFU'}
GATE = Decimal('2.5')
MIN_FB = Decimal('1.33')


def wdl(a, b):
    return 'h' if a > b else 'a' if a < b else 'd'


def hit_ft(leg, opt, H, A):
    m, k, L = leg['market'], opt['key'], Decimal(str(leg.get('L') or 0))
    if m == 'HAD': return k == wdl(H, A)
    if m == 'HHAD': return k == wdl(Decimal(H) + L, Decimal(A))
    if m == 'TTG': return k == f's{min(H + A, 7)}'
    if m == 'DD': return (H == A) if k == 'had_d' else (Decimal(H) + L == A)
    if m == 'HAFU': return k[1] == wdl(H, A)
    return None


def structure_ok(m1, m2):
    ms = {m1, m2}
    return (m1 == m2 and m1 in SAME_ALLOWED) or (m1 != m2 and ms in ALLOWED)


def effective_multiples(legs):
    branches = list(itertools.product(legs[0]['options'], legs[1]['options']))
    nb = len(branches)
    return [(a, b, Decimal(a['odds']) * Decimal(b['odds']) / nb) for a, b in branches]


def audit(data, require_reasons=True):
    """返回 (errors, notes)。data 格式见 tools/audit_recommendations.py。"""
    errs, notes, finals = [], [], {}
    for g in data.get('groups', []):
        n, legs = g['name'], g['legs']
        if len(legs) != 2:
            errs.append(f'{n}: 腿数{len(legs)}≠2'); continue
        if legs[0]['num'] == legs[1]['num']:
            errs.append(f'{n}: 两腿同一场')
        if g['sport'] == 'football' and not structure_ok(legs[0]['market'], legs[1]['market']):
            errs.append(f'{n}: 结构{legs[0]["market"]}+{legs[1]["market"]}不在八结构内')
        for lg in legs:
            finals[lg['num']] = lg
            if require_reasons and len([r for r in lg.get('reasons', []) if str(r).strip()]) < 2:
                errs.append(f'{n} {lg["num"]}: 理由少于2条')
            for o in lg['options']:
                if g['sport'] == 'football' and Decimal(o['odds']) < MIN_FB:
                    errs.append(f'{n} {lg["num"]} {o["label"]}@{o["odds"]}<1.33')
        for a, b, eff in effective_multiples(legs):
            tag = f'{n}: 分支{a["label"]}×{b["label"]} 整单实际倍数{eff.quantize(Decimal("0.0001"))}'
            (errs if eff <= GATE else notes).append(tag + ('≤2.5' if eff <= GATE else ' 通过'))
    for dl in data.get('dream', []):
        lg = finals.get(dl['num'])
        if lg:
            H, A = map(int, dl['score'].split(':'))
            if not any(hit_ft(lg, o, H, A) for o in lg['options']):
                errs.append(f'梦想单 {dl["num"]} 比分{dl["score"]}与同场最终方向{[o["label"] for o in lg["options"]]}矛盾')
    return errs, notes
