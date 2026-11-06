"""Compare live official facts with an immutable publication; never silently replaces selections."""
import itertools
import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from ..storage.monitoring import MonitoringStore
from ..storage.publications import PublicationsStore
from ..storage.research import ResearchStore
from .publications import fresh_input
from .recommendations import all_directions
from .research import confirmed_sources, fingerprint, json_text, line_for, match_key, moment, option_catalog, validate_evidence
from .audit import GATE

TZ = ZoneInfo('Asia/Shanghai')


def compare_quotes(bundle, source, now):
    matches = {match_key(match): match for match in source['football'] + source['basketball']}
    catalogs = {key: {option['id']: option for option in option_catalog(match)} for key, match in matches.items()}
    changes, seen = [], set()
    for leg in all_directions(bundle, include_structures=True):
        if leg['option_id'] in seen:
            continue
        seen.add(leg['option_id'])
        identity = {'num': leg['num'], 'match_key': leg['match_key'], 'option_id': leg['option_id']}
        match = matches.get(leg['match_key'])
        if not match:
            changes.append(identity | {'kind': 'identity', 'severity': 'critical',
                'message': '比赛身份或开赛时间发生变化，原选项需重新核实', 'before': leg['kickoff'], 'after': '当前身份未匹配'})
            continue
        if moment(match['kickoff']) <= moment(now):
            changes.append(identity | {'kind': 'closed', 'severity': 'closed',
                'message': '已到开赛时点，停止新增赛前判断；原票保留复盘', 'before': '赛前', 'after': '已开赛'})
            continue
        option = catalogs[leg['match_key']].get(leg['option_id'])
        if option is None:
            current_line = line_for(match, leg['market'])
            changes.append(identity | {'kind': 'line_or_sale', 'severity': 'critical',
                'message': '盘口、可售性、完整报价或过关资格变化，原方向不能继续当作实时可用',
                'before': leg.get('L') or leg['label'], 'after': current_line or match['status']})
            continue
        before = [str(o['odds']) for o in leg['options']]
        after = [str(o['odds']) for o in option['audit_options']]
        if [Decimal(value) for value in before] != [Decimal(value) for value in after]:
            changes.append(identity | {'kind': 'price', 'severity': 'review',
                'message': '官方价格已变化，需要新的AI决策与审核；原价不改写',
                'before': '／'.join(before), 'after': '／'.join(after)})
        elif abs(option['p'] - leg['p_mkt']) > 1e-12:
            changes.append(identity | {'kind': 'market_baseline', 'severity': 'review',
                'message': '完整市场基准变化，需要重审；不由赔率推断资金流或伤停',
                'before': f'{leg["p_mkt"]:.2%}', 'after': f'{option["p"]:.2%}'})
    for group in bundle['groups']:
        options = [catalogs.get(leg['match_key'], {}).get(leg['option_id']) for leg in group['legs']]
        if not all(options):
            continue
        branches = list(itertools.product(*(option['audit_options'] for option in options)))
        multiples = [Decimal(str(a['odds'])) * Decimal(str(b['odds'])) / len(branches) for a, b in branches]
        if any(value <= GATE for value in multiples):
            changes.append({'num': group['name'], 'match_key': '', 'option_id': '', 'kind': 'hard_gate',
                'severity': 'critical', 'message': '当前价格已不满足每个分支整单实际倍数严格>2.5',
                'before': '／'.join(group['effective_multiples']), 'after': '／'.join(map(str, multiples))})
    if bundle['dream_legs'] and any(moment(leg['kickoff']) > moment(now) for leg in bundle['dream_legs']):
        if not any(row.get('formula') == '4x1' for row in source.get('football_allup', {}).get('CRS', [])):
            changes.append({'num': '梦想单', 'match_key': '', 'option_id': '', 'kind': 'dream_rule',
                'severity': 'critical', 'message': '当前CRS 4x1规则支持未核实，需重审', 'before': '已核4x1', 'after': '待核'})
    return changes


def _escape(text):
    from html import escape
    return escape(str(text), quote=False).replace('|', '\\|')


class RecheckService:
    def __init__(self, config, fetcher, analyst=None, store=None):
        self.config, self.fetcher, self.analyst = config, fetcher, analyst
        self.root = Path(config['PROJECT_DIR'])
        self.store = store or MonitoringStore(config['DATA_DIR'])
        self.publications = PublicationsStore(config['DATA_DIR'])
        self.research = ResearchStore(config['DATA_DIR'])

    def run(self, task, now=None, on_event=None):
        now = moment(now or datetime.now(TZ))
        started = time.monotonic()
        publication = self.publications.get(task['publication_id'])
        current = self.publications.current(publication['business_date']) if publication else None
        if not publication or not current or current['id'] != publication['id'] or current['status'] != 'published':
            raise ValueError('只复核当前有效发布版本')
        original = self.root / 'runs' / publication['business_date'] / publication['id']
        bundle = json.loads((original / 'recommendations.json').read_text(encoding='utf-8'))
        source = fresh_input(self.fetcher, publication['business_date'], now)
        changes = compare_quotes(bundle, source, now)
        folder = self.root / 'runs' / publication['business_date'] / task['id']
        folder.mkdir(parents=True, exist_ok=False, mode=0o700)
        (folder / 'official.json').write_text(json_text(source), encoding='utf-8')
        (folder / 'original-publication.json').write_text(json_text(publication), encoding='utf-8')
        findings, gaps, deferred, ai_incomplete = [], [], [], []
        prefs = self.store.preferences()
        original_items = {item['match_key']: item for item in self.research.items(publication['task_id'])}
        live_matches = {match_key(match): match for match in source['football'] + source['basketball']}
        selected, selected_options = {}, {}
        for leg in all_directions(bundle, include_structures=True):
            selected.setdefault(leg['match_key'], leg)
            selected_options.setdefault(leg['match_key'], {})[leg['option_id']] = leg
        for key, leg in sorted(selected.items(), key=lambda row: row[1]['kickoff']):
            if self.store.cancelled(task['id']):
                raise ValueError('临场复核已取消，已保存资料保留')
            remaining = (moment(leg['kickoff']) - now).total_seconds()/60
            if not 0 < remaining <= prefs['lead_minutes']:
                continue
            old = (original_items.get(key) or {}).get('payload') or {}
            match = live_matches.get(key)
            if match is None:
                continue
            if not task['lineup_enabled']:
                if not any(d['id'] == 18 and d['status'] == 'verified' for d in old.get('dimensions', [])):
                    gaps.append(leg['num'] + ' 正式首发尚未核实；未启用临场AI证据研究')
                continue
            cached = self.store.evidence(publication['id'], key)
            evidence, provenance, using_cache = None, None, False
            if cached and 0 <= (now-moment(cached['as_of'])).total_seconds() < prefs['interval_minutes']*60:
                using_cache = True
                evidence = cached['payload'].get('evidence', cached['payload'])
                provenance = cached['payload'].get('ai')
            else:
                if self.analyst is None or time.monotonic()-started >= 300:
                    deferred.append(leg['num'])
                    continue
                try:
                    returned = self.analyst(match, old, folder / key, now,
                                           lambda: self.store.cancelled(task['id']), on_event)
                    if isinstance(returned, dict) and 'result' in returned and 'provider' in returned:
                        provenance = {name: value for name, value in returned.items() if name != 'result'}
                        returned = returned['result']
                    evidence = validate_evidence(returned, match, now)
                    artifact = folder / (key + '.json')
                    saved = {'evidence': evidence, 'ai': provenance}
                    artifact.write_text(json_text(saved), encoding='utf-8')
                    self.store.cache(publication['id'], key, now.isoformat(), saved, str(artifact.relative_to(self.root)))
                except Exception as exc:
                    gaps.append(leg['num'] + ' AI临场证据未完成：' + type(exc).__name__)
                    ai_incomplete.append(leg['num'])
                    continue
            findings.append({'match_key': key, 'num': leg['num'], 'as_of': cached['as_of'] if using_cache else now.isoformat(),
                             'evidence': evidence, 'ai': provenance, 'cached': using_cache})
            # Evidence research covers the full current catalog, not just the original
            # selections. Only a sourced veto of an exact published option is actionable.
            confirmed = confirmed_sources(evidence)
            for assessment in evidence['assessments']:
                original_leg = selected_options[key].get(assessment['option_id'])
                if (original_leg is None or assessment['decision'] != 'veto'
                        or not confirmed.intersection(assessment['source_ids'])):
                    continue
                changes.append({'num': original_leg['num'], 'match_key': key,
                    'option_id': original_leg['option_id'], 'kind': 'evidence_veto', 'severity': 'critical',
                    'message': '临场AI返回有时点已核实反证，否决原票选项；需人工撤销或重审，未自动换腿',
                    'before': original_leg['label'],
                    'after': '；'.join(assessment['reasons']) + '；风险：' + assessment['risk']})
            before = {d['id']: d for d in old.get('dimensions', [])}
            for dimension in evidence['dimensions']:
                if dimension['id'] not in (4, 18) or dimension['status'] not in ('verified', 'partial', 'conflict'):
                    continue
                previous = before.get(dimension['id'], {})
                if any(previous.get(field) != dimension[field] for field in ('home', 'away', 'status')):
                    changes.append({'num': leg['num'], 'match_key': key, 'option_id': '', 'kind': 'evidence',
                        'severity': 'review', 'message': '伤停/首发核查记录更新，需人工核对来源和原方案影响',
                        'before': previous.get('home', '待核') + '；' + previous.get('away', '待核'),
                        'after': dimension['home'] + '；' + dimension['away']})
            lineup = next((d for d in evidence['dimensions'] if d['id'] == 18), {})
            if lineup.get('status') != 'verified':
                gaps.append(leg['num'] + ' 正式首发仍未核实，不将部分资料当作正式名单')
        if deferred:
            gaps.append('本轮预算/分析器不足，待继续核查：' + '、'.join(deferred))
        state = 'needs_review' if any(change['severity'] in ('critical', 'review') for change in changes) else (
            'incomplete' if gaps else 'checked_quotes')
        result = {'id': task['id'], 'publication_id': publication['id'], 'business_date': publication['business_date'],
                  'as_of': now.isoformat(), 'changes': changes, 'findings': findings, 'gaps': gaps,
                  'deferred': deferred, 'ai_incomplete': ai_incomplete, 'state': state, 'changed_sha256': fingerprint(changes),
                  'research_scope': f'仅开赛前{prefs["lead_minutes"]}分钟内比赛',
                  'original_unchanged': True, 'automatic_replacement': False, 'actual_stake': None, 'actual_return': None}
        (folder / 'recheck.json').write_text(json_text(result), encoding='utf-8')
        lines = ['# 临场复核', '', f'原发布版本：{publication["id"]}；时点：{now.isoformat()}',
                 '只对照事实与AI返回的证据记录，未替换推荐，原票与原价格保留。', '',
                 '| 比赛/时段 | 变化 | 原值 | 当前记录 |', '| --- | --- | --- | --- |']
        lines += ['| ' + ' | '.join(_escape(c[field]) for field in ('num', 'message', 'before', 'after')) + ' |'
                  for c in changes]
        lines += ['', '## 待核资料', *['- ' + _escape(gap) for gap in gaps]]
        (folder / 'recheck.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return result
