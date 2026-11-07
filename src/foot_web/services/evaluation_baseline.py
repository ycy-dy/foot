"""Frozen market benchmark, not advice. No AI/evidence gate or evaluation-time selection."""
import copy
import math

from . import engine
from .research import exclusion_reason, fingerprint, line_for, match_key, moment

SCHEMA = {'version': '026.1', 'unit': 'normalized-ticket', 'selection': 'highest-joint-p_mkt-per-period',
          'label': 'market benchmark not advice', 'probability': 'independent-market-approximation'}
SCHEMA_SHA256 = fingerprint(SCHEMA)


def _clocks(source, as_of):
    cutoff = moment(as_of)
    if moment(source['as_of']) > cutoff:
        raise ValueError('baseline source时点晚于发布')
    for sport in ('football', 'basketball'):
        meta = source[sport + '_meta']
        if meta.get('stale') or moment(meta['captured_at']) > cutoff:
            raise ValueError('baseline source抓取时点无效或未来')
        if moment(meta['source_update']) > cutoff:
            raise ValueError('baseline source更新时间晚于发布')


def baseline_ticket(group, day):
    """Standard review settlement shape, intentionally outside the recommendation ledger."""
    legs = copy.deepcopy(group['legs'])
    return {'business_date': day, 'kind': '足球最终串' if group['sport'] == 'football' else '篮球最终串',
            'title': group['name'], 'label': SCHEMA['label'], 'reference_only': True,
            'p_mkt': group['p_mkt_joint'], 'legs': legs, 'hit': None,
            'model_probability': None, 'EV': None, 'actual_stake': None, 'actual_return': None,
            'sim_cost': 2 * math.prod(len(leg['options']) for leg in legs)}


def freeze_baseline(source, manifest, as_of):
    _clocks(source, as_of)
    if manifest.get('runtime_provider') not in ('codex', 'harness'):
        raise ValueError('baseline provider无效')
    eligible = {sport: [m for m in source[sport] if not exclusion_reason(m, as_of)]
                for sport in ('football', 'basketball')}
    pools = [('football', '足球' + name, pool) for name, pool, _ in engine.football_pools(eligible['football'])]
    pools += [('basketball', '篮球' + label, [m for m in eligible['basketball'] if m['period'] == period])
              for period, label in (('early', '早场'), ('late', '晚场'))]
    tickets, periods = [], []
    for sport, title, pool in pools:
        options = engine.football_options if sport == 'football' else engine.basketball_options
        candidates = [c for c in engine.pairs(pool, options, sport) if c['gate_ok']]
        periods.append({'title': title, 'sport': sport, 'eligible_matches': len(pool),
                        'legal_candidates': len(candidates), 'available': bool(candidates)})
        if not candidates:
            continue
        candidate, legs = candidates[0], []
        matches = {m['num']: m for m in pool}
        for row in candidate['legs']:
            match, option = matches[row['num']], row['opt']
            legs.append({'sport': sport, 'number': match['num'], 'official_id': match['official_id'],
                         'match_key': match_key(match), 'home': match['home'], 'away': match['away'],
                         'matchup': match['home'] + ' VS ' + match['away'], 'kickoff': match['kickoff'],
                         'match_date': match['kickoff'][:10], 'market': '双平' if option['code'] == 'DD' else option['code'],
                         'goal_line': line_for(match, option['code']), 'options': copy.deepcopy(option['audit_options']),
                         'p_mkt': option['p'], 'model_probability': None, 'EV': None})
        ticket = baseline_ticket({'sport': sport, 'name': title, 'legs': legs, 'p_mkt_joint': candidate['p']}, source['business_date'])
        ticket.update(structure=candidate['struct'], branch_products=candidate['prods'],
                      effective_multiples=candidate['eff'])
        tickets.append(ticket)
    payload = {'schema': SCHEMA, 'schema_sha256': SCHEMA_SHA256, 'business_date': source['business_date'],
               'as_of': moment(as_of).isoformat(), 'source_as_of': source['as_of'],
               'source_sha256': fingerprint(source), 'manifest': copy.deepcopy(manifest),
               'manifest_sha256': fingerprint(manifest), 'runtime_provider': manifest['runtime_provider'],
               'label': SCHEMA['label'], 'reference_only': True, 'tickets': tickets, 'periods': periods}
    return payload | {'content_sha256': fingerprint(payload)}


def validate_baseline(baseline, publication, audit):
    """Check frozen identities only. Never enumerate or repair a historical baseline."""
    if baseline['schema'] != SCHEMA or baseline['schema_sha256'] != SCHEMA_SHA256:
        raise ValueError('baseline schema hash不匹配')
    digest = fingerprint({k: v for k, v in baseline.items() if k != 'content_sha256'})
    if digest != baseline['content_sha256'] or digest != publication['baseline_sha256']:
        raise ValueError('baseline content hash不匹配')
    source = audit['source']
    _clocks(source, publication['created_at'])
    if not (baseline['source_sha256'] == audit['source_sha256'] == fingerprint(source)):
        raise ValueError('baseline source hash不匹配')
    if baseline['source_as_of'] != source['as_of'] or moment(baseline['as_of']) > moment(publication['created_at']):
        raise ValueError('baseline事前时点不匹配')
    manifest = publication['manifest']
    if (baseline['manifest'] != manifest or audit.get('manifest', manifest) != manifest
            or baseline['manifest_sha256'] != fingerprint(manifest)):
        raise ValueError('baseline manifest hash不匹配')
    provider = manifest.get('runtime_provider')
    if provider not in ('codex', 'harness') or baseline['runtime_provider'] != provider:
        raise ValueError('baseline provider mismatch')
    if publication.get('ai_decision', {}).get('provider', provider) != provider:
        raise ValueError('AI provider mismatch')
    if baseline['business_date'] != publication['business_date'] or source['business_date'] != baseline['business_date']:
        raise ValueError('baseline业务日不匹配')
    if baseline['label'] != SCHEMA['label'] or baseline['reference_only'] is not True:
        raise ValueError('baseline不是市场研究标记')
    for ticket in baseline['tickets']:
        if ticket['business_date'] != baseline['business_date'] or len(ticket['legs']) != 2:
            raise ValueError('baseline ticket结构无效')
        for row in [ticket, *ticket['legs']]:
            p = row.get('p_mkt')
            if isinstance(p, bool) or not isinstance(p, (float, int)) or not math.isfinite(p) or not 0 <= p <= 1:
                raise ValueError('baseline probability缺失或无效')
        if any(moment(leg['kickoff']) <= moment(baseline['as_of']) for leg in ticket['legs']):
            raise ValueError('baseline已开赛')
    return baseline['tickets']
