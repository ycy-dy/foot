import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from foot_web import create_app

FIX = Path(__file__).parent / 'fixtures'
ANALYSIS_ASOF = datetime(2026, 11, 4, 12, tzinfo=ZoneInfo('Asia/Shanghai'))


def research_payload(match):
    from foot_web.services.research import option_catalog
    options = match.get('research_options') or option_catalog(match)
    return {
        'hypothesis': '未查到充分非赔率依据，仅按市场基准', 'counterargument': '缺关键阵容核实',
        'failure_paths': ['核心未出场使实力假设失效', '比赛节奏与预期相反'],
        'quality_gaps': ['没有正式首发', '独立预测模型未运行'], 'sources': [],
        'dimensions': [{'id': i, 'status': 'unknown', 'home': '待核', 'away': '待核',
                        'impact': '仅作条件判断', 'source_ids': []} for i in range(1, 24)],
        'assessments': [{'option_id': o['id'], 'decision': 'retain',
                         'reasons': ['未查到非赔率依据，仅按市场基准', '本项需要比赛沿对应结算路径发展'],
                         'source_ids': [], 'risk': '阵容与路径未核实', 'withdraw_if': '出现已确认的反向证据时撤销',
                         'mechanism': '对照本项比分或分差条件，阵容未知使结论不稳定'}
                        for o in options],
        'scenarios': [{'name': '核心缺阵', 'condition': '官方确认核心缺阵', 'impact': '关键进攻组织待核查',
                       'action': '重新审查相关方向', 'source_ids': []}],
    }


def audited_research_payload(match):
    """Synthetic offline evidence, with the real audit shape, for positive gates.

    These are explicit test doubles, not claims of fetched production facts.
    Keep research_payload source-free for missing-evidence negative tests.
    """
    payload = research_payload(match)
    payload['sources'] = [
        {'id': 'official', 'url': 'https://www.uefa.com/news/',
         'title': '离线模拟官方名单与战术记录（非线上抓取）', 'tier': 'L1',
         'group_id': 'fixture-official', 'published_at': ANALYSIS_ASOF.isoformat(),
         'effective_at': ANALYSIS_ASOF.isoformat()},
        {'id': 'statistics', 'url': 'https://www.fifa.com/tournaments/',
         'title': '离线模拟独立赛程和表现记录（非线上抓取）', 'tier': 'L2',
         'group_id': 'fixture-statistics', 'published_at': ANALYSIS_ASOF.isoformat(),
         'effective_at': ANALYSIS_ASOF.isoformat()},
    ]
    for row in payload['dimensions']:
        row.update(status='verified', home='模拟已核实主队名单与表现',
                   away='模拟已核实客队名单与表现', impact='模拟对照比赛路径',
                   source_ids=['official', 'statistics'])
    for row in payload['assessments']:
        row['source_ids'] = ['official', 'statistics']
        row['reasons'] = ['模拟官方名单支持人员可用性假设', '模拟独立表现记录支持所述比赛路径']
    payload['quality_gaps'] = ['独立预测模型未运行']
    return payload


def audited_research_response(prompt):
    if '=== RECOMMENDATION DECISION INPUT ===\n' in prompt:
        return decision_response(prompt)
    match = json.loads(prompt.split('=== MATCH INPUT ===\n')[1])
    return audited_research_payload(match)


def decision_response(prompt):
    """Offline AI double: explicit ranked choices and returned rationale per option."""
    from foot_web.services.audit import hit_ft
    from foot_web.services.research import fingerprint
    context = json.loads(prompt.split('=== RECOMMENDATION DECISION INPUT ===\n')[1])
    options, slots = context['options'], context['slots']
    chosen = {slot: rows[0] if rows else None for slot, rows in slots.items()}
    finals = []
    for slot, row in chosen.items():
        if slot.startswith('final:') and row:
            finals += [options[key] for key in row['option_ids']]
    for slot in slots:
        if not slot.startswith('dream:'):
            continue
        compatible = []
        for row in slots[slot]:
            leg = options[row['option_ids'][0]]
            home, away = map(int, leg['label'].split(':'))
            if all(any(hit_ft(final, option, home, away) for option in final['options'])
                   for final in finals if final['match_key'] == leg['match_key']):
                compatible.append(row)
        chosen[slot] = compatible[0] if compatible else None
    return {'context_sha256': fingerprint(context), 'summary': '模拟AI已审阅候选，按市场基准排序并保留条件风险。',
            'vetoes': [], 'choices': [{'slot': slot, 'candidate_id': row['id'] if row else None,
                                     'reason': '模拟AI审阅证据后保留最高合规市场基准候选'} for slot, row in chosen.items()],
            'assessments': [{'option_id': key, 'reasons': ['模拟AI：对照冻结来源中的名单及表现记录，不上调市场基准',
                                                        '模拟AI：需沿本项结算路径发展，缺阵使路径失效'],
                             'source_ids': [s['id'] for item in context['evidence']
                                             if item['match_key'] == options[key]['match_key']
                                             for s in (item.get('payload') or {}).get('sources', [])],
                              'risk': '模拟AI返回：阵容和比赛路径仍待核实',
                             'withdraw_if': '模拟AI返回：出现已确认反证或停售即撤销',
                             'mechanism': '模拟AI返回：对照进球或分差条件核查比赛机制'} for key in options]}


def research_response(prompt):
    if '=== RECOMMENDATION DECISION INPUT ===\n' in prompt:
        return decision_response(prompt)
    match = json.loads(prompt.split('=== MATCH INPUT ===\n')[1])
    return research_payload(match)


class FakeFetcher:
    def __init__(self):
        self.data = {s: json.loads((FIX / f'{s}_2026-11-04.json').read_text()) for s in ('football', 'basketball')}

    def get(self, sport, force=False):
        return self.data[sport], {'source_update': 'fixture', 'captured_at': 'fixture', 'stale': False}


class FakeIdentity:
    def __init__(self):
        self.next = {'union_id': 'u1', 'user_id': 'admin1', 'name': '管理员甲'}

    def exchange(self, code):
        if code == 'bad':
            raise ValueError('bad code')
        return self.next


def copy_rules(destination):
    """Copy only current policy contracts; never production state or legacy V6."""
    from foot_web.services.versions import RULE_FILES
    root = Path(__file__).resolve().parents[1]
    for name in RULE_FILES:
        target = Path(destination) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / name).read_bytes())


def set_policy_provider(project, provider):
    """Override only an isolated test policy; never mutate the production contract."""
    import yaml
    from foot_web.services.versions import POLICY_BASE
    path = Path(project) / (POLICY_BASE + '.yaml')
    policy = yaml.safe_load(path.read_text())
    policy['runtime_provider'] = provider
    policy['decision']['runtime_provider'] = provider
    policy['decision']['providers'] = [provider]
    path.write_text(yaml.safe_dump(policy, allow_unicode=True, sort_keys=False))


@pytest.fixture
def cfg(tmp_path):
    project = tmp_path / 'isolated-project'
    copy_rules(project)
    return {'DINGTALK_CLIENT_ID': 'cid', 'DINGTALK_CLIENT_SECRET': 'sec', 'DINGTALK_CORP_ID': 'corp',
            'DINGTALK_REDIRECT_URI': 'http://localhost/auth/dingtalk/callback', 'DINGTALK_AGENT_ID': '1',
            'FOOT_ALLOWED_USER_IDS': 'viewer1', 'FOOT_ADMIN_USER_IDS': 'admin1', 'FOOT_NOTIFY_USER_IDS': '',
            'FOOT_SECRET_KEY': 'test-secret', 'FOOT_PORT': '5020', 'DATA_DIR': str(tmp_path),
            'PROJECT_DIR': str(project)}


@pytest.fixture
def identity():
    return FakeIdentity()


@pytest.fixture
def app(cfg, identity):
    return create_app(cfg, fetcher=FakeFetcher(), identity=identity, analysis_launcher=lambda config, task_id: os.getpid())


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, identity, user_id='admin1', name='管理员甲', code='ok'):
    identity.next = {'union_id': 'u-' + user_id, 'user_id': user_id, 'name': name}
    client.get('/auth/dingtalk/begin')
    with client.session_transaction() as s:
        state = s['oauth_state']
    return client.get(f'/auth/dingtalk/callback?state={state}&authCode={code}')
