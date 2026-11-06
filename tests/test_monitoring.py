import json
import os
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import ANALYSIS_ASOF, FakeFetcher


def test_monitoring_is_opt_in_and_fires_are_idempotent(tmp_path):
    from foot_web.storage.monitoring import MonitoringStore
    store = MonitoringStore(tmp_path)
    assert not store.preferences()['enabled'] and not store.preferences()['lineup_enabled']
    settings = store.save_preferences({'enabled': '1', 'lead_minutes': '60', 'interval_minutes': '10'}, 'admin1')
    assert settings['enabled'] and not settings['lineup_enabled']
    one, created = store.begin('check-one', 'pub', 'scheduled-slot', 'admin1', False)
    two, again = store.begin('check-two', 'pub', 'scheduled-slot', 'admin1', False)
    assert created and not again and one['id'] == two['id']
    with pytest.raises(ValueError):
        store.save_preferences({'lead_minutes': '3', 'interval_minutes': '0'}, 'admin1')


def test_price_and_line_changes_are_facts_not_new_recommendations():
    from foot_web.services.rechecks import compare_quotes
    from foot_web.services.research import option_catalog, match_key
    from foot_web.data.markets import parse_basketball
    fetcher = FakeFetcher()
    match = parse_basketball(fetcher.data['basketball'])[0]
    option = next(o for o in option_catalog(match) if o['code'] == 'HDC')
    leg = {'match_key': match_key(match),
           'option_id': option['id'], 'num': match['num'], 'market': option['code'], 'L': option['line'],
           'label': option['label'], 'options': option['audit_options'], 'p_mkt': option['p'], 'kickoff': match['kickoff']}
    bundle = {'groups': [], 'singles': [{'leg': leg}], 'six': [], 'structures': [], 'dream_legs': []}
    source = {'football': [], 'basketball': [match]}
    assert compare_quotes(bundle, source, ANALYSIS_ASOF) == []
    match['hdc']['line'] = '-99.5'
    changes = compare_quotes(bundle, source, ANALYSIS_ASOF)
    assert changes and changes[0]['severity'] == 'critical'
    assert '盘口' in changes[0]['message']
    assert leg['L'] != '-99.5'


def test_monitoring_views_require_admin_for_mutation(client, app, identity):
    from conftest import login
    assert client.get('/research/monitoring').status_code == 302
    login(client, identity, 'viewer1', '查看者')
    assert client.get('/research/monitoring').status_code == 403
    with client.session_transaction() as session:
        csrf = session['csrf']
    client.post('/logout', data={'csrf': csrf})
    login(client, identity)
    assert client.get('/research/monitoring').status_code == 200
    assert client.post('/research/monitoring', data={'enabled': '1'}).status_code == 400


def test_scheduler_dispatches_one_live_recheck_per_bucket_only_after_opt_in(cfg, tmp_path):
    from foot_web.engine.operations import Operations
    from foot_web.engine.rechecks import RecheckTasks
    from foot_web.services.notifications import Notifications
    from foot_web.storage.publications import PublicationsStore
    config = cfg | {'PROJECT_DIR': str(tmp_path)}
    calls = []
    tasks = RecheckTasks(config, launcher=lambda task_id: calls.append(task_id) or os.getpid())
    notifications = Notifications(config, notifier=object())
    operations = Operations(config, tasks, notifications)
    publication = {'id': 'publication-fixture', 'task_id': 'fixture', 'check_id': 'check-fixture',
                   'business_date': '2026-11-04', 'status': 'published', 'created_at': ANALYSIS_ASOF.isoformat(),
                   'actor': 'admin1', 'previous_id': None}
    PublicationsStore(config['DATA_DIR']).promote(publication, [])
    folder = tmp_path / 'runs/2026-11-04/publication-fixture'
    folder.mkdir(parents=True)
    leg = {'kickoff': (ANALYSIS_ASOF+timedelta(minutes=30)).isoformat()}
    (folder / 'recommendations.json').write_text(json.dumps({
        'groups': [{'legs': [leg]}], 'singles': [], 'six': [], 'dream_legs': [], 'structures': []}))
    operations.tick(ANALYSIS_ASOF)
    assert calls == []
    tasks.store.save_preferences({'enabled': '1', 'lead_minutes': '60', 'interval_minutes': '10'}, 'admin1')
    operations.tick(ANALYSIS_ASOF)
    operations.tick(ANALYSIS_ASOF)
    assert len(calls) == 1
    first = tasks.store.list()[0]
    tasks.store.update(first['id'], status='succeeded', message='fixture')
    operations.tick(ANALYSIS_ASOF+timedelta(minutes=11))
    assert len(calls) == 2


@pytest.mark.parametrize('veto_target', ['first_selected', 'second_selected', 'unselected', 'unconfirmed'])
def test_live_evidence_veto_only_flags_the_published_option(tmp_path, monkeypatch, veto_target):
    import copy
    from conftest import research_payload
    from foot_web.data.markets import parse_football
    from foot_web.services.rechecks import RecheckService
    from foot_web.services.recommendations import _leg
    from foot_web.services.research import json_text, match_key, moment, option_catalog

    match = parse_football(FakeFetcher().data['football'])[0]
    now = moment(match['kickoff']) - timedelta(minutes=30)
    options = option_catalog(match)[:3]
    for option in options:
        option.update(reasons=['仅按市场基准', '原选项需要对应比赛路径'], sources=[],
                      evidence_state='market_only', risk='风险待核', withdraw_if='确认反证时撤销', mechanism='原路径')
    legs = [_leg(match, option) for option in options]
    bundle = {'groups': [], 'singles': [{'leg': legs[0]}], 'six': [{'leg': legs[1]}],
              'structures': [], 'dream_legs': []}
    config = {'PROJECT_DIR': str(tmp_path), 'DATA_DIR': str(tmp_path / 'state')}
    service = RecheckService(config, object())
    publication = {'id': 'publication-veto', 'task_id': 'analysis-veto', 'check_id': 'check-veto',
                   'business_date': match['business_date'], 'created_at': now.isoformat(),
                   'status': 'published', 'actor': 'admin1', 'previous_id': None}
    service.publications.promote(publication, [])
    folder = tmp_path / 'runs' / match['business_date'] / publication['id']
    folder.mkdir(parents=True)
    original = folder / 'recommendations.json'
    original.write_text(json_text(bundle))
    frozen = original.read_bytes()
    old = research_payload(match)
    old['sources'] = [{'id': 'official', 'url': 'https://www.uefa.com/news', 'title': '离线测试来源',
                       'published_at': (now-timedelta(minutes=1)).isoformat(), 'effective_at': now.isoformat(),
                       'group_id': 'fixture', 'tier': 'L1'}]
    # Keep injury/lineup dimensions unchanged so they cannot mask an ignored veto.
    old['dimensions'][17].update(status='verified', source_ids=['official'], home='已核实', away='已核实')
    new = copy.deepcopy(old)
    if veto_target != 'unconfirmed':
        new['dimensions'][12].update(status='verified', source_ids=['official'], home='新增反证', away='新增反证')
    index = {'first_selected': 0, 'second_selected': 1, 'unselected': 2, 'unconfirmed': 0}[veto_target]
    assessment = next(row for row in new['assessments'] if row['option_id'] == legs[index]['option_id'])
    assessment.update(decision='veto', source_ids=[] if veto_target == 'unconfirmed' else ['official'],
                      risk='已确认原玩法路径矛盾', withdraw_if='立即撤销')
    service.research.items = lambda task_id: [{'match_key': match_key(match), 'payload': old}]
    calls = []
    service.analyst = lambda *args: calls.append(True) or copy.deepcopy(new)
    monkeypatch.setattr('foot_web.services.rechecks.fresh_input',
                        lambda *args: {'football': [match], 'basketball': []})
    task = {'id': 'recheck-first', 'publication_id': publication['id'], 'lineup_enabled': True}
    result = service.run(task, now=now)
    if veto_target in ('first_selected', 'second_selected'):
        assert result['state'] == 'needs_review'
        assert len(result['changes']) == 1
        change = result['changes'][0]
        assert change['kind'] == 'evidence_veto' and change['severity'] == 'critical'
        assert change['option_id'] == legs[index]['option_id']
        assert change['match_key'] == legs[index]['match_key']
        assert not result['automatic_replacement']
        cached = service.run(task | {'id': 'recheck-cached'}, now=now+timedelta(minutes=1))
        assert len(calls) == 1 and cached['findings'][0]['cached']
        assert cached['changes'] == result['changes']
    elif veto_target == 'unselected':
        assert result['state'] == 'checked_quotes' and result['changes'] == []
    else:
        assert result['state'] == 'incomplete' and result['changes'] == []
        assert result['gaps'] and result['ai_incomplete']
    assert original.read_bytes() == frozen
