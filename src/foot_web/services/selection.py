"""Structured AI selection contract, candidate identity and immutable provenance checks."""
import copy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .recommendations import all_directions, build_bundle, selection_fingerprint
from .evidence_confidence import passes
from .research import ANALYSIS_REQUEST, confirmed_sources, fingerprint, json_text

TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 4000}
IDS = {'type': 'array', 'items': TEXT, 'uniqueItems': True}


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


DECISION_SCHEMA = obj({
    'context_sha256': TEXT,
    'summary': TEXT,
    'vetoes': {'type': 'array', 'items': obj({'option_id': TEXT, 'reason': TEXT, 'source_ids': IDS})},
    'choices': {'type': 'array', 'items': obj({'slot': TEXT, 'candidate_id': {'type': ['string', 'null']}, 'reason': TEXT})},
    'assessments': {'type': 'array', 'items': obj({
        'option_id': TEXT, 'reasons': {'type': 'array', 'items': TEXT, 'minItems': 2},
        'source_ids': IDS, 'risk': TEXT, 'withdraw_if': TEXT, 'mechanism': TEXT})},
})
VALIDATOR = Draft202012Validator(DECISION_SCHEMA)


def candidate_legs(candidate):
    return candidate['legs'] if 'legs' in candidate else [candidate]


def candidate_id(candidate):
    ids = [leg['option_id'] for leg in candidate_legs(candidate)]
    return ids[0] if len(ids) == 1 else fingerprint(ids)[:24]


def decision_context(source, items, manifest, as_of):
    catalog = {}
    bundle = build_bundle(source, items, manifest, as_of, catalog=catalog)
    options, slots = {}, {}
    for slot, candidates in catalog.items():
        rows = []
        for candidate in candidates:
            legs = candidate_legs(candidate)
            for leg in legs:
                # Evidence is supplied once per match below; do not repeat its
                # prose and source records on every market alternative.
                options[leg['option_id']] = {key: copy.deepcopy(leg[key]) for key in (
                    'option_id', 'match_key', 'sport', 'num', 'home', 'away', 'kickoff', 'period',
                    'market', 'L', 'label', 'options', 'p_mkt', 'evidence_confidence')}
            rows.append({'id': candidate_id(candidate), 'option_ids': [leg['option_id'] for leg in legs],
                         'p_mkt': candidate.get('p_mkt_joint', candidate.get('p_mkt'))})
        slots[slot] = rows
    # Team identity and original evidence are shared; do not repeat them in every score/market option.
    slim_options = {key: {field: leg[field] for field in
                         ('option_id', 'match_key', 'sport', 'num', 'market', 'L', 'label', 'options', 'p_mkt', 'evidence_confidence')}
                    for key, leg in options.items()}
    matches = {item['match_key']: {key: item['match'][key] for key in
                                  ('sport', 'num', 'business_date', 'kickoff', 'period', 'league', 'home', 'away')}
               for item in items}
    context = {'business_date': source['business_date'], 'manifest': manifest, 'options': slim_options,
               'analysis_request': copy.deepcopy(source.get('analysis_request')),
               'matches': matches, 'slots': slots,
               'dream_4x1': any(row.get('formula') == '4x1' for row in source.get('football_allup', {}).get('CRS', [])),
               'match_status': [{'match_key': m['num'], 'exclusion': m['exclusion']} for m in bundle['matches']],
               'evidence': [{'match_key': item['match_key'], 'payload': item.get('payload')} for item in items]}
    return context


def make_decision_prompt(context):
    return (
        '用户总任务：' + ANALYSIS_REQUEST + '\n'
        '本轮“今天”指业务日' + context['business_date'] + '。当前是总任务的最终推荐阶段，'
        '现行项目规则原文在输入analysis_request.rules中（旧输入可能未保存），必须遵守其最新修订。\n'
        '你是最终推荐决策员。逐场价格盲证据已冻结；现在必须审阅全部合规候选，返回真实取舍，不得只解释程序首选。'
        '每个候选已通过evidence_confidence>=70的版本化证据政策门槛；这是证据评分不是胜率，不能自行改分或绕过关键阻断。'
        '市场基准p_mkt不是模型概率、价值证据或收益保证，不能上调；模型概率和EV保持null。'
        '逐个slot明确返回candidate_id（无剩余合规项才为null）和取舍理由。先审阅证据、提出有来源的风险否决，'
        '再在每个slot未被否决的候选中选最高p_mkt；仅同概率可自由取舍，不能无依据跳过高排名项。'
        'vetoes只能引用该选项所属比赛已冻结source_ids，不得把缺资料当作已确认反证。'
        '每个最终实际采用选项都需assessments：至少两条理由、机制、主要失败路径risk、撤销条件withdraw_if；'
        '至少一条理由引用非赔率来源。没有来源须明确“仅按市场基准”，不可编造。'
        '所有slot都须覆盖：final为分段二串一，single在该段不能成串时使用；six为六类，structure为结构研究。'
        'dream先排除与已选足球final（无串时为实际前两名单场）结算矛盾的比分，再按p_mkt选择每场最佳，'
        '最后程序按p_mkt取四场；不足四场或未核CRS4x1不成单。dream slot候选为完整比分目录，须自行核路径。'
        '相同选项的理由必须一致；仅输出schema要求的JSON，不展示隐藏思维链。'
        '\ncontext_sha256=' + fingerprint(context) + '\n=== RECOMMENDATION DECISION INPUT ===\n'
        + json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False))


def validate_decision(value, context, source, items, manifest, as_of):
    error = next(VALIDATOR.iter_errors(value), None)
    if error:
        raise ValueError('AI推荐决策结构无效')
    if value['context_sha256'] != fingerprint(context):
        raise ValueError('AI推荐输入身份不一致')
    if not value['summary'].strip() or any(not row['reason'].strip() for row in value['choices'] + value['vetoes']):
        raise ValueError('AI总结、取舍或否决理由不能为空')
    options = context['options']
    vetoes = {row['option_id']: row for row in value['vetoes']}
    assessments = {row['option_id']: row for row in value['assessments']}
    choices = {row['slot']: row for row in value['choices']}
    if len(vetoes) != len(value['vetoes']) or len(assessments) != len(value['assessments']):
        raise ValueError('AI选项意见重复')
    if len(choices) != len(value['choices']) or set(choices) != set(context['slots']):
        raise ValueError('AI决策未完整覆盖候选栏目')
    sources = {item['match_key']: {s['id']: s for s in (item.get('payload') or {}).get('sources', [])} for item in items}
    confirmed = {item['match_key']: confirmed_sources(item.get('payload') or {}) for item in items}
    for row in list(vetoes.values()) + list(assessments.values()):
        option = options.get(row['option_id'])
        if not option:
            raise ValueError('AI引用未知选项')
        if any(key not in sources.get(option['match_key'], {}) for key in row['source_ids']):
            raise ValueError('AI引用未知或跨比赛来源')
        if 'reason' in row and not set(row['source_ids']) & confirmed.get(option['match_key'], set()):
            raise ValueError('AI事实风险否决须有已核实非赔率证据，不能把资料缺口当已确认反证')
        if any(not r.strip() for r in row.get('reasons', [])) or any(not row[k].strip() for k in ('risk', 'withdraw_if', 'mechanism') if k in row):
            raise ValueError('AI理由或风险不能为空')

    def select(slot, candidates):
        allowed = [candidate for candidate in candidates
                   if not any(leg['option_id'] in vetoes for leg in candidate_legs(candidate))]
        chosen_id = choices[slot]['candidate_id']
        if not allowed:
            if chosen_id is not None:
                raise ValueError('AI选择了已否决或路径矛盾候选')
            return None
        chosen = next((row for row in allowed if candidate_id(row) == chosen_id), None)
        if chosen is None:
            raise ValueError('AI未选择真实合规候选')
        probability = lambda c: c.get('p_mkt_joint', c.get('p_mkt'))
        if probability(chosen) < max(map(probability, allowed)) - 1e-12:
            raise ValueError('AI无风险否决却跳过更高市场基准候选')
        return copy.deepcopy(chosen)

    bundle = build_bundle(source, items, manifest, as_of, selector=select)
    for leg in all_directions(bundle, include_structures=True):
        if not passes(leg.get('evidence_confidence')):
            raise ValueError('实际推荐腿未通过证据可信度硬门槛')
        opinion = assessments.get(leg['option_id'])
        if opinion is None:
            raise ValueError('实际推荐腿缺少AI返回理由')
        if not set(opinion['source_ids']) & confirmed.get(leg['match_key'], set()):
            raise ValueError('最终推荐必须引用已核实非赔率来源，不能仅按市场基准绕过70%门槛')
    return copy.deepcopy(value)


def apply_decision(value, context, source, items, manifest, as_of, provenance):
    validate_decision(value, context, source, items, manifest, as_of)
    vetoes = {row['option_id'] for row in value['vetoes']}
    choices = {row['slot']: row['candidate_id'] for row in value['choices']}
    opinions = {row['option_id']: row for row in value['assessments']}

    def select(slot, candidates):
        return next((copy.deepcopy(c) for c in candidates if candidate_id(c) == choices[slot]
                     and not any(leg['option_id'] in vetoes for leg in candidate_legs(c))), None)

    bundle = build_bundle(source, items, manifest, as_of, selector=select)
    sources = {item['match_key']: {s['id']: s for s in (item.get('payload') or {}).get('sources', [])} for item in items}
    for leg in all_directions(bundle, include_structures=True):
        opinion = opinions[leg['option_id']]
        for key in ('reasons', 'risk', 'withdraw_if', 'mechanism'):
            leg[key] = copy.deepcopy(opinion[key])
        leg['sources'] = [sources[leg['match_key']][key] for key in opinion['source_ids']]
        if not passes(leg.get('evidence_confidence')):
            raise ValueError('AI最终应用的推荐腿未通过证据可信度硬门槛')
        leg['evidence_state'] = 'ai_sourced_pending_manual_review' if leg['sources'] else 'market_only'
        leg['ai_decision_sha256'] = provenance['validated_sha256']
    bundle['audit_input']['singles'] = [row['leg'] for row in bundle['singles']]
    bundle['audit_input']['six'] = [row['leg'] for row in bundle['six'] if row['leg']]
    bundle['ai_decision'] = copy.deepcopy(provenance)
    bundle['ai_summary'] = value['summary']
    bundle['reference_only'] = False
    bundle['selection_sha256'] = selection_fingerprint(bundle)
    return bundle


def load_decision(folder):
    """Verify returned/validated artifacts, not just a draft's success flag."""
    folder = Path(folder)
    envelope = json.loads((folder / 'ai-decision.json').read_text(encoding='utf-8'))
    context = json.loads((folder / 'decision-context.json').read_text(encoding='utf-8'))
    provenance = {key: value for key, value in envelope.items() if key != 'result'}
    artifact_dir = provenance['artifact_dir']
    if Path(artifact_dir).name != artifact_dir or not artifact_dir.startswith('decision-'):
        raise ValueError('AI工件路径无效')
    artifact = folder / artifact_dir
    provider = provenance['provider']
    if provider not in ('claude', 'codex'):
        raise ValueError('AI提供方无效')
    if provenance.get('model') is not None:
        raise ValueError('CLI未核实实际模型身份')
    for name, key in [('prompt.txt', 'input_sha256'), ('schema.json', 'schema_sha256'),
                      (provider + '.response.json', 'response_sha256'), ('validated.json', 'validated_sha256')]:
        if hashlib.sha256((artifact / name).read_bytes()).hexdigest() != provenance[key]:
            raise ValueError('AI决策工件哈希不一致')
    validated = json.loads((artifact / 'validated.json').read_text(encoding='utf-8'))
    raw = json.loads((artifact / (provider + '.response.json')).read_text(encoding='utf-8'))
    if validated != envelope['result'] or raw != validated:
        raise ValueError('AI返回与已验证结果不一致')
    if json.loads((artifact / 'schema.json').read_text(encoding='utf-8')) != DECISION_SCHEMA:
        raise ValueError('AI决策schema不一致')
    if json.loads((artifact / 'attempts.json').read_text(encoding='utf-8')) != provenance['attempts']:
        raise ValueError('AI尝试记录不一致')
    if not provenance['attempts'] or provenance['attempts'][-1] != {'provider': provider, 'status': 'succeeded', 'code': 'ok'}:
        raise ValueError('AI缺少真实成功尝试')
    if validated['context_sha256'] != fingerprint(context):
        raise ValueError('AI决策上下文哈希不一致')
    if make_decision_prompt(context) != (artifact / 'prompt.txt').read_text(encoding='utf-8'):
        raise ValueError('AI决策上下文与实际提示不一致')
    return envelope, context
