"""Fresh official-data audit and explicit administrator publication; never places bets."""
import copy
import fcntl
import json
import math
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..data.fetcher import Fetcher
from ..data import markets
from ..storage.publications import PublicationsStore
from ..storage.research import ResearchStore
from .recommendations import all_directions, render_report
from .selection import apply_decision, decision_context, load_decision
from .research import fingerprint, json_text, match_key, moment, option_catalog
from .versions import rules_manifest, same_version

TZ = ZoneInfo('Asia/Shanghai')


class PublicationError(ValueError):
    pass


def fresh_input(fetcher, day, now):
    raw, metadata, parsed = {}, {}, {}
    for sport, parser in [('football', markets.parse_football), ('basketball', markets.parse_basketball)]:
        raw[sport], metadata[sport] = fetcher.get(sport, force=True)
        meta = metadata[sport]
        try:
            age = (moment(now) - moment(meta['captured_at'])).total_seconds()
        except (TypeError, ValueError, KeyError):
            raise PublicationError('官方刷新缺少可核验抓取时点') from None
        if meta.get('stale') or age < -5 or age > 120:
            raise PublicationError('官方刷新不可用或快照过期，不能审核发布')
        parsed[sport] = [m for m in parser(raw[sport]) if m['business_date'] == day]
    return {
        'business_date': day, 'as_of': moment(now).isoformat(), 'football': parsed['football'],
        'basketball': parsed['basketball'], 'football_meta': metadata['football'], 'basketball_meta': metadata['basketball'],
        'football_allup': (raw['football'].get('value') or {}).get('allUpList', {}),
        'basketball_allup': (raw['basketball'].get('value') or {}).get('allUpList', {}),
        'raw': raw,
    }


def normalized_tickets(bundle, publication_id):
    tickets = []

    def ticket(title, kind, legs, ledger):
        rows = []
        for leg in legs:
            rows.append({
                'sport': leg['sport'], 'number': leg['num'], 'matchup': leg['matchup'].replace('（客）', '').replace('（主）', ''),
                'home': leg['home'], 'away': leg['away'], 'kickoff': leg['kickoff'], 'match_date': leg['kickoff'][:10],
                'market': '双平' if leg['market'] == 'DD' else leg['market'], 'goal_line': leg['L'],
                'options': copy.deepcopy(leg['options']), 'p_mkt': leg['p_mkt'],
                'reasons': copy.deepcopy(leg['reasons']), 'sources': copy.deepcopy(leg['sources']),
                'risk': leg['risk'], 'withdraw_if': leg['withdraw_if'], 'model_probability': None, 'EV': None,
                'ai_decision_sha256': leg['ai_decision_sha256'],
            })
        tickets.append({'business_date': bundle['business_date'], 'published_at': bundle['as_of'],
                        'run_id': publication_id, 'publication_id': publication_id, 'title': title,
                        'kind': kind, 'ledger': ledger, 'legs': rows, 'hit': None, 'published': True,
                        'p_mkt': _joint(legs), 'model_probability': None, 'EV': None,
                        'sim_cost': 2 * math.prod(len(leg['options']) for leg in legs),
                        'legs_total': len(legs), 'legs_hit': None, 'theoretical_return': None,
                        'actual_stake': None, 'actual_return': None,
                        'ai_decision': copy.deepcopy(bundle['ai_decision'])})

    for group in bundle['groups']:
        ticket(group['name'], '足球最终串' if group['sport'] == 'football' else '篮球最终串', group['legs'], 'headline')
    for row in bundle['singles']:
        leg = row['leg']
        ticket(row['period_name'] + ' 单场方向', '足球单场方向' if leg['sport'] == 'football' else '篮球单场方向', [leg], 'single')
    for row in bundle['six']:
        if row['leg']:
            ticket('六类方向 · ' + row['category'], row['category'], [row['leg']], 'six')
    for row in bundle['structures']:
        if row['group']:
            ticket(row['period'] + ' ' + row['structure'], '足球结构研究', row['group']['legs'], 'structure')
    if bundle['dream_legs']:
        ticket('比分4串1梦想单', '梦想单', bundle['dream_legs'], 'dream')
    return tickets


def _joint(legs):
    value = 1.0
    for leg in legs:
        value *= leg['p_mkt']
    return value


class PublicationService:
    def __init__(self, config, fetcher=None, clock=None):
        self.config = config
        self.root = Path(config['PROJECT_DIR'])
        self.data = Path(config['DATA_DIR'])
        self.store = PublicationsStore(self.data)
        self.research = ResearchStore(self.data)
        self.fetcher = fetcher or Fetcher(self.data)
        self.clock = clock or (lambda: datetime.now(TZ))

    def draft(self, task_id):
        task = self.research.store.analysis(task_id)
        if not task:
            raise KeyError(task_id)
        workflow = self.research.workflow(task_id)
        if task['status'] != 'succeeded' or not workflow:
            raise PublicationError('仅完整结构化草稿可以审核，旧任务请重新分析')
        path = self.root / 'runs' / task['business_date'] / task_id
        try:
            bundle = json.loads((path / 'recommendations.draft.json').read_text(encoding='utf-8'))
            envelope, context = load_decision(path)
            items = self.research.items(task_id)
            expected_context = decision_context(workflow['source'], items, workflow['manifest'], bundle['as_of'])
            if expected_context != context:
                raise ValueError('AI候选上下文与冻结逐场证据不一致')
            provenance = {key: value for key, value in envelope.items() if key != 'result'}
            expected = apply_decision(envelope['result'], context, workflow['source'], items,
                                      workflow['manifest'], bundle['as_of'], provenance)
            if bundle != expected:
                raise ValueError('草稿与真实AI返回决策不一致')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise PublicationError('缺少有效且一致的AI推荐决策，请重新分析：' + type(exc).__name__) from None
        return task, workflow, path, bundle

    def check(self, task_id, actor, now=None, persist=True):
        raise PublicationError('分析与推荐体系已删除，审核和新发布已停用')

    def publish(self, task_id, check_id, actor, confirmed=False, now=None):
        if not confirmed:
            raise PublicationError('发布前请确认已人工核对证据来源、时点和撤销条件')
        with (self.data / 'publication.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            existing = self.store.by_check(check_id)
            if existing:
                if existing['task_id'] != task_id:
                    raise PublicationError('审核任务不匹配')
                return existing, True
            checked = self.store.check(check_id)
            if not checked or checked['task_id'] != task_id or not checked['passed']:
                raise PublicationError('没有本任务通过的审核记录')
            fresh = self.check(task_id, actor, now=now, persist=False)
            if not fresh['passed'] or fresh['selection_sha256'] != checked['selection_sha256']:
                raise PublicationError('发布前复核发现数据、选项或规则变化，请重新审核并确认')
            bundle = fresh['bundle']
            publication_id = 'publication-' + datetime.now(TZ).strftime('%Y%m%dT%H%M%S%f') + '-' + uuid.uuid4().hex[:8]
            folder = self.root / 'runs' / bundle['business_date'] / publication_id
            previous = self.store.current(bundle['business_date'])
            publication = {'id': publication_id, 'task_id': task_id, 'check_id': check_id,
                           'business_date': bundle['business_date'], 'created_at': fresh['created_at'], 'actor': actor,
                           'previous_id': previous['id'] if previous else None, 'status': 'published',
                           'folder': str(folder), 'selection_sha256': fresh['selection_sha256'],
                           'manifest': bundle['manifest'], 'ai_decision': copy.deepcopy(bundle['ai_decision'])}
            tickets = normalized_tickets(bundle, publication_id)
            folder.mkdir(parents=True, mode=0o700, exist_ok=False)
            decision_source = self.root / 'runs' / bundle['business_date'] / task_id
            envelope, context = load_decision(decision_source)
            artifacts = {'report.md': render_report(bundle, self.research.items(task_id), published=True),
                         'recommendations.json': json_text(bundle), 'tickets.json': json_text(tickets),
                         'audit.json': json_text(fresh), 'publication.json': json_text(publication),
                         'ai-decision.json': json_text(envelope), 'decision-context.json': json_text(context)}
            for artifact in (decision_source / envelope['artifact_dir']).iterdir():
                if artifact.is_file() and artifact.name in ('prompt.txt', 'schema.json', 'claude.response.json',
                                                           'codex.response.json', 'validated.json', 'attempts.json'):
                    artifacts[envelope['artifact_dir'] + '/' + artifact.name] = artifact.read_text(encoding='utf-8')
            for name, text in artifacts.items():
                (folder / name).parent.mkdir(parents=True, exist_ok=True)
                with (folder / name).open('x', encoding='utf-8') as handle:
                    handle.write(text)
            promoted, created = self.store.promote(publication, tickets)
            self.store.store.update_analysis(task_id, message='草稿已审核发布为新版本：' + publication_id)
            self.store.store.event('analysis_published', actor, detail={'publication_id': publication_id, 'task_id': task_id})
            return promoted, not created
