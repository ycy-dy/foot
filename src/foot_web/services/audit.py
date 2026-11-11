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
    from .evidence_confidence import passes
    from . import conditional_pairs
    errs, notes, finals = [], [], {}
    strict_evidence = data.get('require_evidence_confidence') is True
    for lg in data.get('singles', []) + data.get('six', []) + data.get('dream_legs', []):
        if strict_evidence and not passes(lg.get('evidence_confidence')):
            errs.append(f'{lg.get("num", "待核")}: 未通过证据可信度硬门槛')
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
            # New recommendation artifacts carry the score contract. Historical
            # settlement-only audit rows have no score and remain immutable.
            conditional = (data.get('conditional_policy_revision') == conditional_pairs.REVISION
                           and conditional_pairs.valid(lg) and conditional_pairs.marked(g))
            if conditional_pairs.marked(lg) and not conditional:
                errs.append(f'{n} {lg["num"]}: 条件推荐声明缺失、越权或不完整')
            if (strict_evidence or 'evidence_confidence' in lg) and not passes(lg.get('evidence_confidence')) and not conditional:
                errs.append(f'{n} {lg["num"]}: 未通过证据可信度硬门槛')
            for o in lg['options']:
                if g['sport'] == 'football' and Decimal(o['odds']) < MIN_FB:
                    errs.append(f'{n} {lg["num"]} {o["label"]}@{o["odds"]}<1.33')
        for a, b, eff in effective_multiples(legs):
            tag = f'{n}: 分支{a["label"]}×{b["label"]} 整单实际倍数{eff.quantize(Decimal("0.0001"))}'
            (errs if eff <= GATE else notes).append(tag + ('≤2.5' if eff <= GATE else ' 通过'))
    dream = data.get('dream', [])
    if strict_evidence and (dream or data.get('dream_legs')):
        dream_legs = data.get('dream_legs', [])
        if len(dream) != 4 or len(dream_legs) != 4 or len({d.get('num') for d in dream}) != 4:
            errs.append('梦想单必须四场不同比赛各一比分，不能缺腿或重复')
        for leg in dream_legs:
            if leg.get('sport') != 'football' or leg.get('market') != 'CRS' or len(leg.get('options', [])) != 1:
                errs.append('梦想单必须为足球CRS单比分4串1')
            if len(leg.get('reasons', [])) < 2 or not leg.get('sources'):
                errs.append('梦想单每腿须两条理由及非赔率来源')
            if any(Decimal(str(o['odds'])) < MIN_FB for o in leg.get('options', [])):
                errs.append('梦想单单项赔率低于1.33')
        if {d.get('num') for d in dream} != {d.get('num') for d in dream_legs}:
            errs.append('梦想单审核比分与实际四腿不一致')
        for dl in dream:
            leg = next((l for l in dream_legs if l.get('num') == dl.get('num')), None)
            if leg and (leg.get('label') != dl.get('score') or not leg.get('options')
                        or Decimal(str(leg['options'][0]['odds'])) != Decimal(str(dl.get('odds', 0)))):
                errs.append('梦想单比分或价格与冻结腿不一致')
    for dl in dream:
        lg = finals.get(dl['num'])
        if lg:
            H, A = map(int, dl['score'].split(':'))
            if not any(hit_ft(lg, o, H, A) for o in lg['options']):
                errs.append(f'梦想单 {dl["num"]} 比分{dl["score"]}与同场最终方向{[o["label"] for o in lg["options"]]}矛盾')
    return errs, notes
