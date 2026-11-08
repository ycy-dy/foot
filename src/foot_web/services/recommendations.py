"""V6 candidate arithmetic; publishable selections require a validated AI selector."""
import copy
from decimal import Decimal

from . import engine
from .audit import audit, hit_ft
from .evidence_confidence import score_evidence, passes
from .research import DIMENSIONS, STATUSES, exclusion_reason, fingerprint, match_key, moment, option_catalog

SIX = [('胜平负', 'HAD'), ('让球', 'HHAD'), ('进球数', 'TTG'), ('二三球', 'TTG'),
       ('半全场', 'HAFU'), ('双平', 'DD')]
MARKET_NAMES = {'HAD': '胜平负', 'HHAD': '让球', 'TTG': '进球数', 'HAFU': '半全场',
                'DD': '双平', 'CRS': '比分', 'MNL': '胜负', 'HDC': '让分胜负', 'HILO': '大小分'}


def _research(item):
    return item.get('payload') or {}


def options_with_evidence(match, item, as_of=None):
    evidence = _research(item)
    assessments = {row['option_id']: row for row in evidence.get('assessments', [])}
    source_map = {row['id']: row for row in evidence.get('sources', [])}
    out = []
    for option in option_catalog(match):
        opinion = assessments.get(option['id'])
        option['vetoed'] = bool(opinion and opinion['decision'] == 'veto')
        option['risk'] = opinion['risk'] if opinion else '缺少本选项的非赔率核查，阵容和比赛路径仍有不确定性'
        option['withdraw_if'] = opinion['withdraw_if'] if opinion else '停售、开赛、身份/盘口改变或出现已确认反向证据时撤销并复核'
        option['mechanism'] = opinion['mechanism'] if opinion else '未核查具体实力传导机制，仅按市场基准'
        option['sources'] = [source_map[key] for key in opinion['source_ids']] if opinion else []
        option['reasons'] = copy.deepcopy(opinion['reasons']) if opinion else [
            '未查到非赔率依据，仅按市场基准',
            f'本项覆盖“{option["label"]}”的官方结算事件；若比赛偏离该比分/分差路径则不命中']
        if not option['sources'] and not any('仅按市场基准' in reason for reason in option['reasons']):
            option['reasons'][0] = '未查到非赔率依据，仅按市场基准；' + option['reasons'][0]
        option['evidence_confidence'] = score_evidence(evidence, option_id=option['id'], as_of=as_of or item.get('as_of'))
        if '_provenance_checks' in item and option['evidence_confidence'] is not None:
            verified = item['_provenance_checks'].get(option['id'], False)
            option['evidence_confidence']['provenance_verified'] = verified
            if not verified:
                option['evidence_confidence']['eligible'] = False
                option['evidence_confidence']['reasons'].append('缺少当前选项的有效磁盘人工复核凭据')
        option['evidence_state'] = 'sourced_pending_manual_review' if option['sources'] else 'market_only'
        option['model_probability'] = None
        option['EV'] = None
        out.append(option)
    return out


def _leg(match, option):
    home, away = match['home'], match['away']
    matchup = f'{home} VS {away}' if match['sport'] == 'football' else f'{away}（客） VS {home}（主）'
    return {'match_key': match_key(match), 'sport': match['sport'], 'num': match['num'],
            'home': home, 'away': away, 'matchup': matchup, 'kickoff': match['kickoff'],
            'business_date': match['business_date'], 'period': match['period'], 'league': match['league'],
            'option_id': option['id'], 'market': option['code'], 'L': option['line'],
            'label': option['label'], 'options': copy.deepcopy(option['audit_options']),
            'p_mkt': option['p'], 'model_probability': None, 'EV': None,
            'reasons': option['reasons'], 'sources': option['sources'], 'evidence_state': option['evidence_state'],
            'risk': option['risk'], 'withdraw_if': option['withdraw_if'], 'mechanism': option['mechanism'],
            'confidence': '证据政策门槛结果', 'evidence_confidence': copy.deepcopy(option.get('evidence_confidence')), 'price_advantage': 'unproven'}


def _final_eligible(match, option):
    if option['code'] == 'CRS' or option['vetoed'] or not passes(option.get('evidence_confidence')):
        return False
    if match['sport'] == 'football':
        alternative = max((o['p'] for o in match['research_options'] if o['code'] != 'CRS' and not o['vetoed']), default=None)
        narrow = option['code'] in ('HAFU', 'TTG', 'DD') or (
            option['code'] == 'HHAD' and abs(Decimal(str(match.get('L') or 0))) >= 2)
        if narrow and (alternative is None or option['p'] < alternative):
            return False
    return True


def _pair(candidate, matches, title, sport):
    legs = [_leg(matches[leg['num']], leg['opt']) for leg in candidate['legs']]
    return {'name': title, 'sport': sport, 'legs': legs, 'structure': candidate['struct'],
            'p_mkt_joint': candidate['p'], 'probability_method': '独立近似，未处理相关性',
            'branch_products': candidate['prods'], 'effective_multiples': candidate['eff'],
            'branches': candidate['branches'], 'confidence': '证据政策门槛结果',
            'model_probability': None, 'EV': None, 'price_advantage': 'unproven'}


def build_bundle(source, items, manifest, as_of, *, selector=None, catalog=None):
    """Enumerate legal alternatives and materialize explicit, validated AI choices.

    Without a selector this is reference-only candidate preparation, never an AI
    decision. catalog captures all slots, including currently unused single/score
    alternatives so AI vetoes can change the final path without another research call.
    """
    def choose(slot, candidates, reference_candidates=None):
        if catalog is not None:
            catalog[slot] = copy.deepcopy(reference_candidates if reference_candidates is not None else candidates)
        return selector(slot, candidates) if selector else (candidates[0] if candidates else None)

    day = source['business_date']
    by_key = {item['match_key']: item for item in items}
    matches = copy.deepcopy(source['football'] + source['basketball'])
    eligible = []
    for match in matches:
        item = by_key.get(match_key(match), {})
        match['research_options'] = options_with_evidence(match, item, as_of)
        match['exclusion'] = exclusion_reason(match, as_of)
        if item.get('status') != 'succeeded' and not match['exclusion']:
            match['exclusion'] = '逐场证据尚未完成'
        if not match['exclusion'] and not any(passes(o.get('evidence_confidence')) for o in match['research_options']):
            match['exclusion'] = '证据可信度未可靠达到70%，不推荐；请补齐时效、关键证据及选项依据'
        if not match['exclusion']:
            eligible.append(match)

    def opts(match):
        return [o for o in match['research_options'] if _final_eligible(match, o)]

    fb = [m for m in eligible if m['sport'] == 'football']
    bk = [m for m in eligible if m['sport'] == 'basketball']
    groups, periods, structures, singles = [], [], [], []
    pools = [('football', f'足球{name}', pool, note) for name, pool, note in engine.football_pools(fb)]
    pools += [('basketball', '篮球' + label, [m for m in bk if m['period'] == key], '')
              for key, label in [('early', '早场'), ('late', '晚场')]]
    for sport, title, pool, note in pools:
        candidates = engine.pairs(pool, opts, sport) if len(pool) >= 2 else []
        accepted = [candidate for candidate in candidates if candidate['gate_ok']]
        mapping = {m['num']: m for m in pool}
        selected = choose('final:' + title, [_pair(c, mapping, title, sport) for c in accepted])
        directions = []
        for match in pool:
            choices = [_leg(match, option) for option in match['research_options']
                       if option['code'] != 'CRS' and not option['vetoed'] and passes(option.get('evidence_confidence'))]
            leg = choose('single:' + match_key(match), choices)
            if leg:
                directions.append(leg)
        reason = '不足两场未开赛可售且证据可信度达70%的比赛，不能成串' if len(pool) < 2 else '没有同时满足风险、玩法与每分支实际倍数>2.5的组合'
        periods.append({'name': title, 'sport': sport, 'count': len(pool), 'note': note,
                        'group': selected, 'reason': None if selected else reason})
        if selected:
            groups.append(selected)
        else:
            directions.sort(key=lambda leg: -leg['p_mkt'])
            singles += [{'period_name': title, 'leg': leg} for leg in directions[:2]]
        if sport == 'football':
            for structure in engine.STRUCT_ORDER:
                choices = [_pair(c, mapping, title + ' ' + structure, sport)
                           for c in accepted if c['struct'] == structure]
                structures.append({'period': title, 'structure': structure,
                                   'group': choose('structure:' + title + ':' + structure, choices)})
    six = []
    for category, code in SIX:
        choices = [_leg(m, option) for m in fb for option in m['research_options']
                   if option['code'] == code and not option['vetoed'] and passes(option.get('evidence_confidence'))
                   and (category != '二三球' or {o['key'] for o in option['audit_options']} == {'s2', 's3'})]
        choices.sort(key=lambda leg: -leg['p_mkt'])
        chosen = choose('six:' + category, choices)
        six.append({'category': category, 'leg': chosen,
                    'reason': None if chosen else '该类没有真实可售、过关及通过风险审查的选项，或AI风险否决'})

    finals = {}
    for group in groups:
        for leg in group['legs']:
            finals.setdefault(leg['num'], []).append(leg)
    for row in singles:
        leg = row['leg']
        if leg['sport'] == 'football':
            finals.setdefault(leg['num'], []).append(leg)
    dream_candidates = []
    for match in fb:
        scores = []
        for option in match['research_options']:
            if option['code'] != 'CRS' or option['vetoed'] or not passes(option.get('evidence_confidence')):
                continue
            H, A = map(int, option['label'].split(':'))
            if all(any(hit_ft(leg, opt, H, A) for opt in leg['options']) for leg in finals.get(match['num'], [])):
                scores.append(option)
        # The context includes all scores; validation additionally checks the
        # final-leg settlement path. A changed final cannot invent a score option.
        chosen = choose('dream:' + match_key(match), [_leg(match, o) for o in scores],
                        [_leg(match, o) for o in match['research_options'] if o['code'] == 'CRS' and not o['vetoed']
                         and passes(o.get('evidence_confidence'))])
        if chosen:
            dream_candidates.append(chosen)
    dream_candidates.sort(key=lambda leg: -leg['p_mkt'])
    supported_4x1 = any(row.get('formula') == '4x1' for row in source.get('football_allup', {}).get('CRS', []))
    dream = dream_candidates[:4] if len(dream_candidates) >= 4 and supported_4x1 else []
    dream_reason = None if dream else '不足四场路径一致的比分选项，或官方CRS 4x1支持尚未核实'
    bundle = {'schema_version': '1.0', 'business_date': day, 'as_of': moment(as_of).isoformat(),
              'manifest': manifest, 'groups': groups, 'periods': periods, 'singles': singles,
              'six': six, 'structures': structures, 'dream_legs': dream, 'dream_reason': dream_reason,
              'matches': matches, 'model_probability': None, 'EV': None, 'reference_only': selector is None}
    bundle['audit_input'] = {'require_evidence_confidence': True, 'groups': groups,
                             'singles': [r['leg'] for r in singles], 'six': [r['leg'] for r in six if r['leg']],
                             'dream_legs': dream, 'dream': [
        {'num': leg['num'], 'score': leg['label'], 'odds': leg['options'][0]['odds']} for leg in dream]}
    errors, notes = audit(bundle['audit_input'])
    bundle['draft_checks'] = {'errors': errors, 'notes': notes, 'published': False}
    bundle['selection_sha256'] = selection_fingerprint(bundle)
    return bundle


def all_directions(bundle, include_structures=False):
    out = [leg for group in bundle['groups'] for leg in group['legs']]
    out += [row['leg'] for row in bundle['singles']]
    out += [row['leg'] for row in bundle['six'] if row['leg']]
    out += bundle['dream_legs']
    if include_structures:
        out += [leg for row in bundle['structures'] if row['group'] for leg in row['group']['legs']]
    return out


def selection_fingerprint(bundle):
    return fingerprint({
        'groups': bundle['groups'], 'singles': bundle['singles'], 'six': bundle['six'],
        'structures': bundle['structures'], 'dream': bundle['dream_legs'], 'manifest': bundle['manifest'],
        'ai_decision': bundle.get('ai_decision'), 'ai_summary': bundle.get('ai_summary'),
    })


def _cell(value):
    # Model-produced prose remains Markdown text, not executable HTML or table structure.
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '\\|').replace('\n', '<br>')


def _leg_text(leg):
    prices = '／'.join(f'{o["label"]}@{o["odds"]}' for o in leg['options'])
    score = leg.get('evidence_confidence') or {}
    quality = str(score.get('evidence_confidence', '待核'))
    return (f'{leg["num"]} {_cell(leg["matchup"])} · {_cell(leg["label"])}（{prices}） · p_mkt {leg["p_mkt"]:.1%}'
            + f' · 证据可信度 {quality}/100（{score.get("version", "无契约")}，非命中概率）')


def render_report(bundle, items, published=False):
    lines = ['# 最终推荐汇总', '',
             f'业务日：{bundle["business_date"]}；决策时点：{bundle["as_of"]}；'
             + ('已通过发布门禁的研究报告。' if published else '分析草稿，未审核、未发布。'),
             '市场基准命中概率来自官方完整市场比例去水，不是独立模型概率；组合为独立近似，未处理相关性。'
             '独立模型未部署，模型概率和EV为null；价格优势未证实。未提交、未下单，不保证命中或收益。', '']
    for period in bundle['periods']:
        lines += ['## ' + period['name'], '']
        group = period['group']
        if group:
            lines += [_leg_text(leg) + '  ' for leg in group['legs']]
            lines += [f'整单实际倍数：{"／".join(group["effective_multiples"])}；'
                      f'联合市场基准约 {group["p_mkt_joint"]:.1%}（独立近似）。证据门槛已通过，模型概率仍未验证。', '']
            for leg in group['legs']:
                lines += [f'- {leg["num"]} 理由：' + '；'.join(_cell(r) for r in leg['reasons']),
                          '', f'  风险：{_cell(leg["risk"])}；撤销条件：{_cell(leg["withdraw_if"])}。', '']
        else:
            lines += [period['reason'], '']
            for row in bundle['singles']:
                if row['period_name'] == period['name']:
                    leg = row['leg']
                    lines += [_leg_text(leg), '', '理由：' + '；'.join(_cell(reason) for reason in leg['reasons']),
                              '', f'风险：{_cell(leg["risk"])}；撤销：{_cell(leg["withdraw_if"])}。', '']
    decision = bundle.get('ai_decision')
    if decision:
        lines += ['', '## AI推荐决策来源', '', _cell(bundle['ai_summary']),
                  '提供方：' + _cell(decision['provider']) + '；输入哈希：' + decision['input_sha256'],
                  '返回哈希：' + decision['response_sha256'] + '；已验证决策哈希：' + decision['validated_sha256'],
                  '尝试：' + _cell('；'.join(a['provider'] + '/' + a['status'] + '/' + a['code'] for a in decision['attempts']))]
    else:
        lines += ['', '仅程序市场参考，非AI推荐，不可发布。']
    lines += ['', '---', '', '## 逐场六类/三类玩法（机械市场参考，非推荐）', '',
              '| 编号 | 时间 | 赛事与对阵 | 胜平负/胜负 | 让球/让分 | 总球/大小分 | 半全场 | 双平 | 比分参考 | 状态/风险 |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for match in bundle['matches']:
        fields = []
        for code in ('HAD' if match['sport'] == 'football' else 'MNL',
                     'HHAD' if match['sport'] == 'football' else 'HDC',
                     'TTG' if match['sport'] == 'football' else 'HILO', 'HAFU', 'DD', 'CRS'):
            choices = [o for o in match['research_options'] if o['code'] == code and not o['vetoed']]
            option = choices[0] if choices else None
            fields.append(_cell(option['label'] + ' ' + '／'.join('@' + str(b['odds']) for b in option['branches']))
                          if option else '不可用/待核')
        matchup = f'{match["home"]} VS {match["away"]}' if match['sport'] == 'football' else f'{match["away"]}（客） VS {match["home"]}（主）'
        state = match['exclusion'] or '证据达标候选，具体评分和风险见逐场附录'
        lines.append('| ' + ' | '.join([match['num'], match['kickoff'], _cell(match['league'] + ' ' + matchup), *fields, _cell(state)]) + ' |')
    lines += ['', '## 六类方向', '']
    for row in bundle['six']:
        lines += ['### ' + row['category'], _leg_text(row['leg']) if row['leg'] else row['reason']]
        if row['leg']:
            leg = row['leg']
            lines += ['理由：' + '；'.join(_cell(r) for r in leg['reasons']),
                      f'风险：{_cell(leg["risk"])}；撤销：{_cell(leg["withdraw_if"])}。']
    lines += ['', '## 八结构研究', '', '| 时段 | 结构 | 两腿/不能成串原因 |', '| --- | --- | --- |']
    for row in bundle['structures']:
        description = '；'.join(_leg_text(leg) + '；理由：' + '；'.join(_cell(r) for r in leg['reasons'])
                               + '；风险：' + _cell(leg['risk']) + '；撤销：' + _cell(leg['withdraw_if'])
                               for leg in row['group']['legs']) if row['group'] else '无通过全部门槛的组合'
        lines.append('| ' + row['period'] + ' | ' + row['structure'] + ' | ' + description + ' |')
    lines += ['', '## 逐场证据与反证', '']
    for item in items:
        match, evidence = item['match'], item.get('payload')
        first_team, second_team = (match['away'], match['home']) if match['sport'] == 'basketball' else (match['home'], match['away'])
        lines += [f'### {match["num"]} {_cell(first_team)} VS {_cell(second_team)}']
        if not evidence:
            lines += [_cell(item['message'])]
            continue
        lines += ['实力假设：' + _cell(evidence['hypothesis']), '最强反证：' + _cell(evidence['counterargument']),
                  '失败路径：' + '；'.join(_cell(s) for s in evidence['failure_paths']),
                  '质量缺口：' + '；'.join(_cell(s) for s in evidence['quality_gaps']),
                  '', '| 维度 | ' + ('客队 | 主队' if match['sport'] == 'basketball' else '主队 | 客队') + ' | 状态与影响 |',
                  '| --- | --- | --- | --- |']
        for dim in evidence['dimensions']:
            first_fact, second_fact = (dim['away'], dim['home']) if match['sport'] == 'basketball' else (dim['home'], dim['away'])
            lines.append(f'| {dim["id"]:02d} {DIMENSIONS[dim["id"]-1]} | {_cell(first_fact)} | {_cell(second_fact)} | '
                         f'{STATUSES[dim["status"]]} · {_cell(dim["impact"])} |')
        contracts = [o.get('evidence_confidence') for o in match.get('research_options', []) if o.get('evidence_confidence')]
        if contracts:
            best = max(contracts, key=lambda c: c['evidence_confidence'])
            lines += ['', '证据政策评分：' + str(best['evidence_confidence']) + '/100；版本：' + best['version'],
                      '评分缺口/门禁：' + '；'.join(_cell(r) for r in best['reasons'])]
        for source in evidence['sources']:
            lines.append(f'- 来源：{_cell(source["title"])} · {_cell(source["url"])} · '
                         f'发布时间 {source["published_at"] or "待核"}；适用时点 {source["effective_at"] or "待核"}。')
    lines += ['', '## 比分4串1梦想单', '']
    if bundle['dream_legs']:
        product, joint = Decimal(1), 1.0
        for leg in bundle['dream_legs']:
            product *= Decimal(str(leg['options'][0]['odds']))
            joint *= leg['p_mkt']
            lines += [_leg_text(leg), '理由：' + '；'.join(_cell(r) for r in leg['reasons']),
                      f'风险：{_cell(leg["risk"])}；撤销：{_cell(leg["withdraw_if"])}。']
        lines += [f'四腿全部正确才命中；组合赔率 {product}；联合市场基准约 {joint:.4%}，独立近似，高风险。']
    else:
        lines += [bundle['dream_reason']]
    return '\n'.join(lines) + '\n'
