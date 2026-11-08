import copy
import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from foot_web.services.versions import RULE_FILES

from conftest import ANALYSIS_ASOF, FakeFetcher, audited_research_response as research_response, login, set_policy_provider
from foot_web import create_app
from foot_web.engine.tasks import AnalysisTasks, run_task
from foot_web.services.publications import PublicationError, PublicationService
from foot_web.services.ledger import Ledger
from foot_web.services.reports import latest_report
from foot_web.services.reviews import ReviewService, load_tickets


class FreshFetcher(FakeFetcher):
    def get(self, sport, force=False):
        raw, _ = super().get(sport, force)
        return raw, {'captured_at': ANALYSIS_ASOF.isoformat(), 'source_update': ANALYSIS_ASOF.isoformat(), 'stale': False}


@pytest.fixture
def researched(cfg, tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    for name in RULE_FILES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes((Path(cfg['PROJECT_DIR']) / name).read_bytes())
    config = cfg | {'PROJECT_DIR': str(root), 'DATA_DIR': str(tmp_path / 'var')}
    set_policy_provider(root, 'codex')
    tasks = AnalysisTasks(config, launcher=lambda *args: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')
    config['FOOT_AI_PROVIDER'] = 'codex'
    run_task(config, task['id'], fetcher=FreshFetcher(),
             generate=lambda provider, prompt, *a, **kw: research_response(prompt), as_of=ANALYSIS_ASOF)
    assert tasks.get(task['id'])['status'] == 'succeeded'
    from conftest import seed_manual_reviews
    seed_manual_reviews(config, task['id'])
    task, _ = tasks.start('2026-11-04', 'admin1', reuse_from=task['id'])
    run_task(config, task['id'], fetcher=FreshFetcher(),
             generate=lambda provider, prompt, *a, **kw: research_response(prompt), as_of=ANALYSIS_ASOF)
    assert tasks.get(task['id'])['status'] == 'succeeded'
    return config, tasks, task, FreshFetcher()


def test_audit_runs_real_script_publish_is_immutable_and_idempotent(researched):
    config, tasks, task, fetcher = researched
    service = PublicationService(config, fetcher)
    draft_folder = Path(config['PROJECT_DIR']) / 'runs' / '2026-11-04' / task['id']
    request = json.loads((draft_folder / 'input.json').read_text())['analysis_request']
    assert request['text'] == '请根据最新分析和推荐体系 分析和推荐今天的比赛'
    assert request['business_date'] == '2026-11-04'
    assert request['project_dir'] == str(Path(config['PROJECT_DIR']).resolve())
    assert all(name in request['rules'] for name in
               RULE_FILES)
    before = (draft_folder / 'report.draft.md').read_bytes()
    checked = service.check(task['id'], 'admin1', now=ANALYSIS_ASOF)
    assert checked['passed'], checked['errors']
    assert checked['script']['exit_code'] == 0 and '审核结果' in checked['script']['output']
    with pytest.raises(PublicationError):
        service.publish(task['id'], checked['id'], 'admin1', confirmed=False, now=ANALYSIS_ASOF)
    publication, reused = service.publish(task['id'], checked['id'], 'admin1', confirmed=True, now=ANALYSIS_ASOF)
    again, duplicate = service.publish(task['id'], checked['id'], 'admin1', confirmed=True, now=ANALYSIS_ASOF)
    assert not reused and duplicate and again['id'] == publication['id']
    assert (draft_folder / 'report.draft.md').read_bytes() == before
    folder = Path(publication['folder'])
    assert all((folder / name).is_file() for name in ['report.md', 'recommendations.json', 'tickets.json', 'audit.json', 'publication.json', 'ai-decision.json', 'decision-context.json'])
    from foot_web.services.research import fingerprint
    frozen_audit = json.loads((folder / 'audit.json').read_text())
    assert 'football' in frozen_audit['source'] and 'basketball' in frozen_audit['source']
    assert 'bundle' not in frozen_audit['source']  # source is official data, not the check envelope
    assert fingerprint(frozen_audit['source']) == frozen_audit['source_sha256']
    from foot_web.services.selection import load_decision
    decision, _ = load_decision(folder)
    tickets_meta = json.loads((folder / 'tickets.json').read_text())
    assert all(row['ai_decision']['validated_sha256'] == decision['validated_sha256'] for row in tickets_meta)
    assert all(leg['ai_decision_sha256'] == decision['validated_sha256'] for row in tickets_meta for leg in row['legs'])
    report = latest_report(config['PROJECT_DIR'], '2026-11-04', config['DATA_DIR'])
    assert report['publication']['id'] == publication['id']
    rows = Ledger(config['PROJECT_DIR'], config['DATA_DIR']).all()
    assert rows and all(row['actual_stake'] is None and row['actual_return'] is None for row in rows)
    assert {row['group'] for row in rows} >= {'最终推荐', '六类方向', '结构研究'}
    assert len(rows) == len(Ledger(config['PROJECT_DIR'], config['DATA_DIR']).all())
    originals, sources = load_tickets(config['PROJECT_DIR'], '2026-11-04', config['DATA_DIR'])
    assert len(originals) == len(rows) and any(s['format'] == 'promoted-normalized-tickets' for s in sources)


@pytest.mark.parametrize('change', ['rules', 'price', 'stopped', 'started', 'stale', 'checkpoint'])
def test_changes_block_release_without_promoting(researched, change):
    config, tasks, task, fetcher = researched
    service = PublicationService(config, fetcher)
    checked = service.check(task['id'], 'admin1', now=ANALYSIS_ASOF)
    assert checked['passed']
    now = ANALYSIS_ASOF
    if change == 'rules':
        path = Path(config['PROJECT_DIR']) / 'AGENTS.md'
        path.write_text(path.read_text() + '\n现行规则已更新。\n')
    elif change in ('price', 'stopped'):
        for group in fetcher.data['football']['value']['matchInfoList']:
            for match in group['subMatchList']:
                if change == 'price':
                    match['had']['h'] = '1.34'
                    match['hhad']['a'] = '1.34'
                    for key in match['ttg']:
                        if key.startswith('s') and key[1:].isdigit():
                            match['ttg'][key] = '1.34'
                else:
                    match['matchStatus'] = 'Closed'
        if change == 'stopped':
            for group in fetcher.data['basketball']['value']['matchInfoList']:
                for match in group['subMatchList']:
                    match['matchStatus'] = 'Closed'
    elif change == 'started':
        now += timedelta(days=1)
    elif change == 'stale':
        original_get = fetcher.get
        fetcher.get = lambda *a, **kw: (original_get(*a, **kw)[0], {'captured_at': ANALYSIS_ASOF.isoformat(), 'source_update': ANALYSIS_ASOF.isoformat(), 'stale': True})
    else:
        folder = Path(config['PROJECT_DIR']) / 'runs' / '2026-11-04' / task['id']
        path = next(p for p in (folder / 'matches').glob('*/*.json')
                    if 'payload' in json.loads(p.read_text()))  # response/attempt artifacts are not checkpoints
        value = json.loads(path.read_text())
        value['payload']['hypothesis'] = '篡改检查点'
        path.write_text(json.dumps(value))
    with pytest.raises(PublicationError):
        service.publish(task['id'], checked['id'], 'admin1', confirmed=True, now=now)
    assert not service.store.list()
    assert latest_report(config['PROJECT_DIR'], '2026-11-04', config['DATA_DIR']) is None


@pytest.mark.parametrize('artifact', ['missing', 'context', 'response', 'validated', 'draft'])
def test_missing_or_tampered_ai_decision_never_passes_publication(researched, artifact):
    config, _, task, fetcher = researched
    folder = Path(config['PROJECT_DIR']) / 'runs' / '2026-11-04' / task['id']
    envelope = json.loads((folder / 'ai-decision.json').read_text())
    if artifact == 'missing':
        (folder / 'ai-decision.json').unlink()
    elif artifact == 'context':
        (folder / 'decision-context.json').write_text('{}')
    elif artifact in ('response', 'validated'):
        name = envelope['provider'] + '.response.json' if artifact == 'response' else 'validated.json'
        path = folder / envelope['artifact_dir'] / name
        value = json.loads(path.read_text())
        value['summary'] = '篡改AI返回'
        path.write_text(json.dumps(value))
    else:
        path = folder / 'recommendations.draft.json'
        draft = json.loads(path.read_text())
        draft['six'][0]['leg']['reasons'] = ['程序偷偷改写理由', '不是AI返回']
        path.write_text(json.dumps(draft))
    service = PublicationService(config, fetcher)
    with pytest.raises(PublicationError, match='AI推荐决策'):
        service.check(task['id'], 'admin1', now=ANALYSIS_ASOF)
    assert not service.store.list()


def test_price_refresh_invalidates_ai_without_silently_reselecting(researched):
    config, _, task, fetcher = researched
    service = PublicationService(config, fetcher)
    _, _, _, draft = service.draft(task['id'])
    # Any full-market change can change proportional de-vig p_mkt, even an
    # unselected price; it must be a renewed AI decision, not a silent refresh.
    match = fetcher.data['football']['value']['matchInfoList'][0]['subMatchList'][0]
    match['had']['d'] = '99.00'
    checked = service.check(task['id'], 'admin1', now=ANALYSIS_ASOF)
    assert not checked['passed']
    assert any('重新获得AI决策' in error for error in checked['errors'])
    assert checked['bundle']['selection_sha256'] == draft['selection_sha256']
    assert checked['bundle']['groups'] == draft['groups']


def test_partial_file_failure_never_becomes_latest_report(researched, monkeypatch):
    config, _, task, fetcher = researched
    service = PublicationService(config, fetcher)
    checked = service.check(task['id'], 'admin1', now=ANALYSIS_ASOF)
    original = Path.open

    def failed(path, *args, **kwargs):
        if path.name == 'tickets.json' and path.parent.name.startswith('publication-'):
            raise OSError('模拟磁盘失败')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', failed)
    with pytest.raises(OSError):
        service.publish(task['id'], checked['id'], 'admin1', confirmed=True, now=ANALYSIS_ASOF)
    assert not service.store.list()
    assert latest_report(config['PROJECT_DIR'], '2026-11-04', config['DATA_DIR']) is None
    assert Ledger(config['PROJECT_DIR'], config['DATA_DIR']).all() == []


def test_new_publication_enters_review_and_does_not_double_count(researched):
    config, _, task, fetcher = researched
    service = PublicationService(config, fetcher)
    checked = service.check(task['id'], 'admin1', now=ANALYSIS_ASOF)
    assert checked['passed'], checked['errors']
    publication, _ = service.publish(task['id'], checked['id'], 'admin1', confirmed=True, now=ANALYSIS_ASOF)
    tickets, _ = load_tickets(config['PROJECT_DIR'], '2026-11-04', config['DATA_DIR'])
    results = {'football': [], 'basketball': []}
    seen = set()
    for ticket in tickets:
        for leg in ticket['legs']:
            key = (leg['sport'], leg['number'])
            if key in seen:
                continue
            seen.add(key)
            row = {'matchNumStr': leg['number'], 'matchDate': leg['match_date'],
                   'allHomeTeam': leg['home'], 'allAwayTeam': leg['away']}
            row.update({'matchResultStatus': '2', 'sectionsNo999': '2:1', 'sectionsNo1': '1:0'}
                       if leg['sport'] == 'football' else {'status': 2, 'finalScore': '100-110'})
            results[leg['sport']].append(row)

    class Results:
        def fetch(self, *a, **kw):
            return copy.deepcopy(results)
    reviewer = ReviewService(config, fetcher=Results())
    one = reviewer.run('2026-11-04', 'review-first')
    two = reviewer.run('2026-11-04', 'review-again')
    ledger = Ledger(config['PROJECT_DIR'], config['DATA_DIR'])
    assert len(one['rows']) == len(two['rows']) == len(ledger.all())
    assert all(row['hit'] is not None for row in ledger.all())
    assert publication['id'] in {row['publication_id'] for row in ledger.all()}
    service.store.withdraw(publication['id'], 'admin1', '复盘后撤销展示，保留原票统计', ANALYSIS_ASOF)
    withdrawn = ledger.all()
    assert all(row['withdrawn'] and row['withdrawal_reason'] for row in withdrawn)
    assert len(withdrawn) == len(one['rows'])


def test_review_publish_routes_require_admin_and_csrf(researched, identity):
    config, _, task, fetcher = researched
    app = create_app(config, fetcher=fetcher, identity=identity, analysis_launcher=lambda *a: os.getpid())
    client = app.test_client()
    endpoint = f'/analysis/{task["id"]}/review'
    assert client.get(endpoint).status_code == 302
    login(client, identity, 'viewer1', '查看者')
    assert client.get(endpoint).status_code == 403
    with client.session_transaction() as session:
        csrf = session['csrf']
    client.post('/logout', data={'csrf': csrf})
    login(client, identity)
    assert client.get(endpoint).status_code == 200
    assert client.post(endpoint, data={'action': 'audit'}).status_code == 400
    assert '审核与发布' in client.get(endpoint).get_data(as_text=True)


def test_late_update_keeps_early_ticket_and_post_start_revision_never_erases_original():
    from foot_web.storage.publications import select_effective_tickets
    early = {'business_date': '2026-11-04', 'kind': '足球最终串', 'title': '足球早中场①',
             'published_at': '2026-11-04T12:00:00+08:00', 'hit': False,
             'legs': [{'kickoff': '2026-11-04 18:00'}]}
    late = {'business_date': '2026-11-04', 'kind': '足球最终串', 'title': '足球晚场②',
            'published_at': '2026-11-04T20:00:00+08:00', 'legs': [{'kickoff': '2026-11-05 02:00'}]}
    after_start = copy.deepcopy(early) | {'published_at': '2026-11-04T21:00:00+08:00', 'hit': True}
    rows = select_effective_tickets([early, late, after_start])
    assert not early.get('superseded') and not late.get('superseded')
    assert after_start['superseded'] and after_start['after_freeze_revision']
    assert early['hit'] is False and len(rows) == 3


def test_same_slot_can_be_replaced_before_kickoff():
    from foot_web.storage.publications import select_effective_tickets
    first = {'business_date': '2026-11-04', 'kind': '胜平负', 'title': '旧方向',
             'published_at': '2026-11-04T12:00:00+08:00', 'legs': [{'kickoff': '2026-11-04 23:00'}]}
    second = copy.deepcopy(first) | {'published_at': '2026-11-04T13:00:00+08:00', 'title': '新方向'}
    select_effective_tickets([first, second])
    assert first['superseded'] and not second.get('superseded')


def test_two_single_directions_in_one_period_are_not_replacements():
    from foot_web.storage.publications import select_effective_tickets
    first = {'business_date': '2026-11-04', 'kind': '足球单场方向', 'title': '足球晚场② 单场方向',
             'published_at': '2026-11-04T12:00:00+08:00',
             'legs': [{'number': '周三001', 'kickoff': '2026-11-04 23:00'}]}
    second = copy.deepcopy(first)
    second['legs'][0]['number'] = '周三002'
    rows = select_effective_tickets([first, second])
    assert len(rows) == 2 and not any(row.get('superseded') for row in rows)


def test_live_recheck_keeps_original_and_reuses_evidence_at_original_time(researched):
    from conftest import research_payload
    from foot_web.engine.rechecks import run_recheck
    from foot_web.services.research import moment
    from foot_web.storage.monitoring import MonitoringStore
    config, _, task, fetcher = researched
    publications = PublicationService(config, fetcher)
    checked = publications.check(task['id'], 'admin1', now=ANALYSIS_ASOF)
    assert checked['passed'], checked['errors']
    publication, _ = publications.publish(task['id'], checked['id'], 'admin1', confirmed=True, now=ANALYSIS_ASOF)
    original = Path(publication['folder']) / 'recommendations.json'
    frozen = original.read_bytes()
    bundle = json.loads(frozen)
    kickoff = min(moment(leg['kickoff']) for leg in bundle['groups'][0]['legs'])
    now = kickoff - timedelta(minutes=30)
    raw_get = fetcher.get
    fetcher.get = lambda *a, **kw: (raw_get(*a, **kw)[0], {
        'captured_at': now.isoformat(), 'source_update': now.isoformat(), 'stale': False})
    store = MonitoringStore(config['DATA_DIR'])
    calls = []

    def analyst(match, old, folder, as_of, cancelled, event):
        calls.append(match['num'])
        payload = research_payload(match)
        payload['sources'] = [{'id': 'lineup', 'url': 'https://example.org/official-lineup',
                              'title': '模拟官方首发', 'published_at': as_of.isoformat(),
                              'effective_at': as_of.isoformat(), 'group_id': 'official-lineup', 'tier': 'L1'}]
        payload['dimensions'][17].update(status='verified', source_ids=['lineup'],
                                         home='模拟官方首发甲', away='模拟官方首发乙')
        return {'provider': 'codex', 'validated_sha256': 'fixture-return', 'result': payload}

    # Inject the clock at the service boundary while exercising the real worker state transitions.
    from foot_web.services.rechecks import RecheckService
    first, _ = store.begin('recheck-first', publication['id'], 'one', 'admin1', True)
    result = RecheckService(config, fetcher, analyst, store).run(first, now)
    assert calls and result['findings'] and any(row['kind'] == 'evidence' for row in result['changes'])
    assert all(f['ai']['provider'] == 'codex' and not f['cached'] for f in result['findings'])
    count = len(calls)
    store.update(first['id'], status='succeeded', payload=result)
    second, _ = store.begin('recheck-second', publication['id'], 'two', 'admin1', True)
    now += timedelta(minutes=1)
    again = RecheckService(config, fetcher, analyst, store).run(second, now)
    assert len(calls) == count
    assert all(f['cached'] and f['as_of'] == result['as_of'] for f in again['findings'])
    assert original.read_bytes() == frozen and not again['automatic_replacement']
    store.update(second['id'], status='succeeded', payload=again)
    cancelled, _ = store.begin('recheck-cancelled', publication['id'], 'three', 'admin1', True)
    store.update(cancelled['id'], cancel_requested=1)
    run_recheck(config, cancelled['id'], fetcher=fetcher, analyst=analyst)
    assert store.get(cancelled['id'])['status'] == 'cancelled'
    assert len(calls) == count and original.read_bytes() == frozen


def test_missing_frozen_baseline_blocks_publish(researched, monkeypatch):
    config, _, task, fetcher = researched
    service = PublicationService(config, fetcher)
    monkeypatch.setattr('foot_web.services.publications.freeze_baseline', lambda *args: None)
    checked = service.check(task['id'], 'admin1', now=ANALYSIS_ASOF)
    assert not checked['passed'] and any('冻结市场基准' in e for e in checked['errors'])
