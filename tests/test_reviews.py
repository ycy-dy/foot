"""Offline fixtures for deterministic review; never read or change production ledgers."""
import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from foot_web.data.results import ResultsFetcher, match_result
from foot_web.services.reviews import ReviewService, option_hit, settle, ticket_id
from foot_web.services.ledger import Ledger


@pytest.fixture
def football():
    return {'matchNumStr': '周三001', 'matchDate': '2026-11-05',
            'allHomeTeam': '主队', 'allAwayTeam': '客队',
            'matchResultStatus': '2', 'sectionsNo999': '2:1', 'sectionsNo1': '1:0'}


@pytest.fixture
def leg():
    return {'sport': 'football', 'number': '周三001', 'matchup': '主队 VS 客队',
            'market': 'HAD', 'goal_line': '',
            'options': [{'key': 'h', 'label': '主胜', 'odds': '1.80'}]}


@pytest.fixture
def ticket(leg):
    return {'business_date': '2026-11-04', 'ledger': 'rec', 'kind': '足球最终串',
            'title': '冻结原票', 'source_file': 'original/report.md', 'snapshot': '2026-11-04T13:00:00+08:00',
            'superseded': False, 'legs': [leg]}


def test_football_identity_and_overnight(leg, football):
    result, note = match_result(leg, '2026-11-04', {'football': [football]})
    assert not note and (result['H'], result['A'], result['hH']) == (2, 1, 1)
    for mutate in ({'matchDate': '2026-11-07'}, {'matchNumStr': '周四001'},
                   {'allHomeTeam': '其他'}, {'matchResultStatus': '0'},
                   {'matchResultStatus': '3'}, {'sectionsNo999': 'bad'}):
        result, note = match_result(leg, '2026-11-04', {'football': [football | mutate]})
        assert result is None and note
    assert match_result(leg | {'match_date': '2026-11-04'}, '2026-11-04', {'football': [football]})[0] is None


def test_ambiguous_results_pending(leg, football):
    for other in (football | {'sectionsNo999': '0:0'}, football | {'matchDate': '2026-11-06'}):
        assert match_result(leg, '2026-11-04', {'football': [football, other]})[0] is None
    assert match_result(leg, '2026-11-04', {'football': [football, copy.deepcopy(football)]})[0] is not None


@pytest.mark.parametrize('market,key,line,expected', [
    ('HAD', 'h', '', True), ('HAD', 'bogus', '', None),
    ('HAD', None, '', None), ('HAD', {'unknown': 1}, '', None),
    ('HHAD', 'd', '-1', True), ('HHAD', 'h', '', None),
    ('HHAD', 'd', '0', False), ('TTG', 's3', '', True),
    ('TTG', 's8', '', None), ('HAFU', 'hh', '', True),
    ('HAFU', 'x', '', None), ('CRS', 's2s1', '', True),
    ('CRS', 's1sh', '', False), ('CRS', 'garbage', '', None),
    ('双平', 'had_d', '', False), ('双平', 'hhad_d', '-1', True),
    ('双平', 'hhad_d', '', None), ('双平', 'bad', '-1', None),
    ('UNKNOWN', 'h', '', None), ('HILO', 'h', '3', None),
    ('HILO', 'h', '', None), ('HILO', 'h', '2.5', True),
    ('HAD', 'h', 'NaN', True), ('HHAD', 'h', 'NaN', None),
])
def test_option_boundaries(leg, football, market, key, line, expected):
    result, _ = match_result(leg, '2026-11-04', {'football': [football]})
    assert option_hit(leg | {'sport': 'basketball' if market == 'HILO' else 'football',
                              'market': market, 'goal_line': line}, {'key': key}, result) is expected


def test_missing_half_and_other_scores(leg, football):
    result, _ = match_result(leg, '2026-11-04', {'football': [football | {'sectionsNo1': ''}]})
    assert option_hit(leg | {'market': 'HAFU'}, {'key': 'hh'}, result) is None
    assert option_hit(leg, {'key': 'h'}, result) is True
    result['H'], result['A'] = 7, 1
    assert option_hit(leg | {'market': 'TTG'}, {'key': 's7'}, result) is True
    assert option_hit(leg | {'market': 'CRS'}, {'key': 's1sh'}, result) is True
    result['H'], result['A'] = 4, 4
    assert option_hit(leg | {'market': 'CRS'}, {'key': 's1sd'}, result) is True
    result['H'], result['A'] = 1, 7
    assert option_hit(leg | {'market': 'CRS'}, {'key': 's1sa'}, result) is True


def test_basketball_order_status_push(leg):
    leg = leg | {'sport': 'basketball', 'matchup': '客队 VS 主队', 'market': 'MNL'}
    row = {'matchNumStr': '周三001', 'matchDate': '2026-11-05',
           'allAwayTeam': '客队', 'allHomeTeam': '主队', 'status': 2, 'finalScore': '100-110'}
    x, _ = match_result(leg, '2026-11-04', {'basketball': [row]})
    assert (x['H'], x['A'], x['score']) == (110, 100, '100:110')
    assert option_hit(leg, {'key': 'h'}, x) is True
    assert option_hit(leg | {'market': 'HDC', 'goal_line': '-10'}, {'key': 'h'}, x) is None
    assert option_hit(leg | {'market': 'HDC', 'goal_line': '-9.5'}, {'key': 'h'}, x) is True
    assert option_hit(leg | {'market': 'HILO', 'goal_line': '209.5'}, {'key': 'h'}, x) is True
    for change in ({'status': 0}, {'status': 3}, {'status': None}, {'finalScore': ''}, {'finalScore': '110-110'}):
        assert match_result(leg, '2026-11-04', {'basketball': [row | change]})[0] is None
    assert match_result(leg | {'matchup': '主队 VS 客队'}, '2026-11-04', {'basketball': [row]})[0] is None


def test_branches_decimal_double_draw(ticket, football):
    double = ticket['legs'][0] | {'market': '双平', 'goal_line': '-1', 'options': [
        {'key': 'had_d', 'label': '平', 'odds': '3.10'},
        {'key': 'hhad_d', 'label': '让平', 'odds': '3.40'}]}
    second = ticket['legs'][0] | {'market': 'TTG', 'options': [
        {'key': 's2', 'label': '2球', 'odds': '4.00'},
        {'key': 's3', 'label': '3球', 'odds': '3.50'}]}
    original = copy.deepcopy(ticket | {'legs': [double, second]})
    settled = settle(original, {'football': [football]})
    assert original == ticket | {'legs': [double, second]}
    assert settled['hit'] is True and len(settled['branches']) == 4
    assert settled['sim_cost'] == 8 and settled['theoretical_return'] == '23.80'
    assert settled['actual_stake'] is None and settled['actual_return'] is None
    assert 'p_mkt' not in settled
    assert settled['settled_legs'][0]['hits'] == [False, True]


def test_pending_not_loss_or_refund(ticket, football):
    unknown = ticket['legs'][0] | {'market': 'UNKNOWN'}
    for changed in (unknown, ticket['legs'][0] | {'options': [{'key': 'bad', 'odds': '2.0'}]}):
        row = settle(ticket | {'legs': [changed]}, {'football': [football]})
        assert row['hit'] is None and row['theoretical_return'] is None
        assert row['settled_legs'][0]['note']
    row = settle(ticket, {'football': [football | {'matchResultStatus': '3'}]})
    assert row['hit'] is None and row['theoretical_return'] is None
    row = settle(ticket | {'legs': [ticket['legs'][0] | {'options': [{'key': 'h', 'odds': None}]}]}, {'football': [football]})
    assert row['hit'] is True and row['theoretical_return'] is None


def test_ticket_id_ignores_settlement_and_ui(ticket, football):
    frozen_id = ticket_id(ticket)
    row = settle(ticket, {'football': [football]})
    row.update(id=999, group='其他', state='miss', ticket_id='untrusted')
    assert ticket_id(row) == frozen_id
    assert ticket_id(row | {'hit': False, 'theoretical_return': '999', 'superseded': True}) == frozen_id
    changed = copy.deepcopy(ticket)
    changed['legs'][0]['options'][0]['odds'] = '1.81'
    assert ticket_id(changed) != frozen_id


def test_fetcher_bounded_paging_and_dates():
    calls = []
    def get(url, timeout):
        calls.append((url, timeout))
        page = len(calls)
        return {'value': {'pages': 2, 'matchResult': [{'matchId': page}]}}
    fetched = ResultsFetcher(http_get=get, timeout=3, max_pages=2).fetch('2026-11-04', sports=['football'])
    assert len(fetched['football']) == 2 and len(fetched['sources']) == 2
    assert 'matchBeginDate=2026-11-04' in calls[0][0] and 'matchEndDate=2026-11-06' in calls[0][0]
    assert all(t == 3 for _, t in calls)
    with pytest.raises(ValueError):
        ResultsFetcher(http_get=get, max_pages=1).fetch('2026-11-04', sports=['football'])
    for payload in ({}, {'value': {'pages': 'oops', 'matchResult': []}},
                    {'value': {'pages': 10000, 'matchResult': []}},
                    {'value': {'pages': 1, 'matchResult': 'bad'}}):
        with pytest.raises(ValueError):
            ResultsFetcher(http_get=lambda *a, **kw: payload).fetch('2026-11-04', sports=['football'])
    def timeout(*a, **kw):
        raise TimeoutError('offline timeout')
    with pytest.raises(TimeoutError):
        ResultsFetcher(http_get=timeout).fetch('2026-11-04')


@pytest.fixture
def workspace(tmp_path, ticket):
    data = tmp_path / 'ledger' / 'data'
    data.mkdir(parents=True)
    original = data / 'records_fixture.jsonl'
    original.write_text(json.dumps(ticket, ensure_ascii=False) + '\n')
    base = data / 'settled_records.json'
    base.write_text(json.dumps([ticket | {'hit': False, 'settled_legs': [], 'sim_cost': 2}]))
    return tmp_path, {'PROJECT_DIR': str(tmp_path), 'DATA_DIR': str(tmp_path / 'var')}, original, base


class FakeFetcher:
    def __init__(self, results):
        self.results = results
    def fetch(self, business_date, sports=None):
        return copy.deepcopy(self.results)


def test_review_versions_overlay_and_frozen(workspace, football):
    root, config, source, base = workspace
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, base)]
    ledger = Ledger(root, config['DATA_DIR'])
    assert ledger.all()[0]['hit'] is False
    service = ReviewService(config, fetcher=FakeFetcher({'football': [football]}))
    first = service.run('2026-11-04', 'review-one')
    folder = Path(first['folder'])
    assert set(p.name for p in folder.iterdir()) == {'tickets.json', 'results.json', 'settlement.json', 'review.md', 'manifest.json'}
    assert first['rows'][0]['hit'] is True and first['per_match'] and first['summary']
    assert len(ledger.all()) == 1 and ledger.all()[0]['hit'] is True
    ledger.all()[0]['hit'] = False
    assert ledger.all()[0]['hit'] is True  # overlay/cache never handed out mutable
    manifest = json.loads((folder / 'manifest.json').read_text())
    assert manifest['sources'][0]['sha256'] == hashes[0]
    assert manifest['engine_version'] and manifest['previous_review_id'] is None
    frozen = {p.name: p.read_bytes() for p in folder.iterdir()}
    service.fetcher = FakeFetcher({'football': [football | {'sectionsNo999': '0:1'}]})
    second = service.run('2026-11-04', 'review-two')
    assert second['rows'][0]['hit'] is False
    assert len(ledger.all()) == 1 and ledger.all()[0]['hit'] is False
    assert json.loads((Path(second['folder']) / 'manifest.json').read_text())['previous_review_id'] == 'review-one'
    assert frozen == {p.name: p.read_bytes() for p in folder.iterdir()}
    assert hashes == [hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, base)]
    with pytest.raises(FileExistsError):
        service.run('2026-11-04', 'review-two')
    db = sqlite3.connect(root / 'var' / 'app.db')
    assert db.execute('select count(*) from review_current').fetchone()[0] == 1
    assert db.execute('select run_id from review_current').fetchone()[0] == 'review-two'
    db.close()


def test_empty_and_fetch_failure_no_overlay(workspace):
    root, config, source, base = workspace
    service = ReviewService(config, fetcher=FakeFetcher({}))
    with pytest.raises(ValueError, match='冻结原票'):
        service.run('2026-11-03', 'empty')
    class Failure:
        def fetch(self, *a, **kw):
            raise TimeoutError('offline')
    service.fetcher = Failure()
    with pytest.raises(TimeoutError):
        service.run('2026-11-04', 'failed')
    assert Ledger(root).all()[0]['hit'] is False
    assert not (root / 'runs/2026-11-04/failed').exists()


def test_fallback_and_superseded_separate(workspace, ticket, football):
    root, config, source, base = workspace
    source.unlink()
    rows = [ticket | {'hit': False, 'id': 1, 'theoretical_return': '999'},
            ticket | {'title': '旧票', 'superseded': True, 'hit': True, 'id': 2}]
    base.write_text(json.dumps(rows))
    review = ReviewService(config, fetcher=FakeFetcher({'football': [football]})).run('2026-11-04', 'fallback')
    tickets = json.loads((Path(review['folder']) / 'tickets.json').read_text())
    assert 'hit' not in tickets[0] and 'id' not in tickets[0]
    assert review['summary']['total']['n'] == 1
    assert review['summary']['superseded']['n'] == 1
    assert len(Ledger(root).query()) == 1
    assert len(Ledger(root).query(include_superseded=True)) == 2


def test_dedupe_drafts_and_unrelated_dates(workspace, ticket, football):
    root, config, source, base = workspace
    source.write_text('\n'.join(json.dumps(r) for r in [ticket, ticket, ticket | {'status': 'draft'},
                                                        ticket | {'business_date': '2026-11-03'}]))
    base.write_text(json.dumps([ticket | {'business_date': '2026-11-03', 'hit': False}]))
    review = ReviewService(config, fetcher=FakeFetcher({'football': [football]})).run('2026-11-04', 'dedupe')
    assert len(review['rows']) == 1
    assert len(Ledger(root).all()) == 2


def test_market_sport_mismatch_and_zero_padded_crs(leg, football):
    x, _ = match_result(leg, '2026-11-04', {'football': [football]})
    assert option_hit(leg | {'market': 'MNL'}, {'key': 'h'}, x) is None
    assert option_hit(leg | {'sport': 'basketball', 'market': 'TTG'}, {'key': 's3'}, x) is None
    assert option_hit(leg | {'market': 'CRS'}, {'key': 's02s01'}, x) is True
    assert option_hit(leg | {'market': 'CRS'}, {'key': 's7s1'}, x) is None


def test_explicit_cancellation_and_invalid_dates(leg, football):
    for change in ({'resultStatus': '比赛取消'}, {'poolStatus': 'Refund'},
                   {'matchDate': '2026-11-05garbage'}, {'matchDate': 'not-a-date'}):
        assert match_result(leg, '2026-11-04', {'football': [football | change]})[0] is None
    utc_leg = leg | {'kickoff': '2026-11-04T18:00:00+00:00'}
    assert match_result(utc_leg, '2026-11-04', {'football': [football]})[0] is not None
    assert match_result(leg | {'match_date': 'bad'}, '2026-11-04', {'football': [football]})[0] is None


def test_p_mkt_preserved_only_if_original(ticket, football):
    ticket['legs'][0]['options'][0]['p_mkt'] = 0.52
    row = settle(ticket | {'p_mkt': 0.52}, {'football': [football]})
    assert row['p_mkt'] == row['settled_legs'][0]['options'][0]['p_mkt'] == 0.52
    assert row['attribution'].startswith('未评估')


def test_missing_half_is_local_not_global(ticket, football):
    had = ticket['legs'][0]
    hafu = had | {'market': 'HAFU', 'options': [{'key': 'hh', 'odds': '3.0'}]}
    results = {'football': [football | {'sectionsNo1': ''}]}
    assert settle(ticket | {'legs': [had]}, results)['hit'] is True
    assert settle(ticket | {'legs': [hafu]}, results)['hit'] is None
    both = settle(ticket | {'legs': [had, hafu]}, results)
    assert both['legs_hit'] == 1 and both['hit'] is None
    assert both['branches'][0]['theoretical_return'] is None


def test_official_closing_handicap_never_used(ticket, football):
    leg = ticket['legs'][0] | {'market': 'HHAD', 'goal_line': '-1',
                              'options': [{'key': 'd', 'odds': '4.0'}]}
    row = settle(ticket | {'legs': [leg]}, {'football': [football | {'goalLine': '-2'}]})
    assert row['hit'] is True and row['theoretical_return'] == '8.00'


def test_ledger_overlay_without_original_and_legacy_db(workspace, football):
    root, config, _, base = workspace
    dbpath = root / 'var/app.db'
    dbpath.parent.mkdir()
    sqlite3.connect(dbpath).close()
    ledger = Ledger(root, config['DATA_DIR'])
    assert len(ledger.all()) == 1
    ReviewService(config, fetcher=FakeFetcher({'football': [football]})).run('2026-11-04', 'new')
    base.unlink()
    assert len(ledger.all()) == 1 and ledger.all()[0]['hit'] is True


def test_failed_write_leaves_previous_overlay(workspace, football, monkeypatch):
    root, config, _, _ = workspace
    service = ReviewService(config, fetcher=FakeFetcher({'football': [football]}))
    service.run('2026-11-04', 'good')
    original_open = Path.open
    def fail_open(self, *a, **kw):
        if self.name == 'manifest.json' and self.parent.name == 'partial':
            raise OSError('fixture disk failure')
        return original_open(self, *a, **kw)
    monkeypatch.setattr(Path, 'open', fail_open)
    with pytest.raises(OSError):
        service.run('2026-11-04', 'partial')
    with sqlite3.connect(root / 'var/app.db') as db:
        assert db.execute('SELECT run_id FROM review_current').fetchone()[0] == 'good'
    assert Ledger(root).all()[0]['hit'] is True


def test_fetch_error_does_not_replace_success(workspace, football):
    root, config, _, _ = workspace
    service = ReviewService(config, fetcher=FakeFetcher({'football': [football]}))
    service.run('2026-11-04', 'success')
    service.fetcher = FakeFetcher({'football': 'malformed'})
    with pytest.raises(ValueError):
        service.run('2026-11-04', 'invalid')
    with sqlite3.connect(root / 'var/app.db') as db:
        assert db.execute('SELECT run_id FROM review_current').fetchone()[0] == 'success'


def test_review_categories_and_missing_odds(workspace, ticket, football):
    _, config, source, _ = workspace
    kinds = ['足球最终串', '足球单场方向', '胜平负', '结构研究', '梦想单']
    rows = [ticket | {'kind': kind} for kind in kinds]
    rows[0]['legs'] = [ticket['legs'][0] | {'options': [{'key': 'h', 'odds': None}]}]
    source.write_text('\n'.join(json.dumps(r) for r in rows))
    result = ReviewService(config, fetcher=FakeFetcher({'football': [football]})).run('2026-11-04', 'categories')
    assert set(result['summary']['by_group']) == {'最终推荐', '单场方向', '六类方向', '结构研究', '梦想单'}
    assert all(s['n'] == 1 for s in result['summary']['by_group'].values())
    assert result['summary']['total']['theoretical_return'] is None
    assert result['summary']['total']['return_pending'] == 1
    text = (Path(result['folder']) / 'review.md').read_text()
    assert '逐场结算' in text and '分栏统计' in text and '未评估' in text
    assert len(Ledger(config['PROJECT_DIR']).stats()['by_group']) == 5


def test_empty_official_results_are_pending_not_zero_return(workspace):
    _, config, _, _ = workspace
    result = ReviewService(config, fetcher=FakeFetcher({'football': []})).run('2026-11-04', 'pending')
    assert result['rows'][0]['hit'] is None
    assert result['summary']['total']['pending'] == 1
    assert result['summary']['total']['settled'] == 0
    assert result['summary']['total']['rate'] is None
    assert result['summary']['total']['theoretical_return'] is None
    assert result['summary']['total']['sim_cost'] == 2


def test_fetcher_response_and_page_change():
    class Response:
        checked = False
        def raise_for_status(self):
            self.checked = True
        def json(self):
            return {'value': {'pages': 0, 'matchResult': []}}
    response = Response()
    results = ResultsFetcher(http_get=lambda *a, **kw: response).fetch('2026-11-04', sports=['basketball'])
    assert response.checked and not results['basketball']
    calls = []
    def get(*args, **kwargs):
        calls.append(1)
        return {'value': {'pages': 2 if len(calls) == 1 else 1, 'matchResult': [{}]}}
    with pytest.raises(ValueError, match='分页变动'):
        ResultsFetcher(http_get=get).fetch('2026-11-04', sports=['football'])
    for config in ({'timeout': 0}, {'timeout': 31}, {'max_pages': 0}, {'max_pages': 1.5},
                   {'page_size': 101}, {'timeout': True}):
        with pytest.raises(ValueError):
            ResultsFetcher(**config)


@pytest.mark.parametrize('run_id', ['../escape', '/tmp/escape', '.', 'bad/name'])
def test_run_id_rejects_path_traversal(workspace, run_id):
    _, config, _, _ = workspace
    with pytest.raises(ValueError):
        ReviewService(config, fetcher=FakeFetcher({})).run('2026-11-04', run_id)


def test_ledger_unknown_return_not_zero_loss():
    unknown = {'state': 'hit', 'sim_cost': 2, 'theoretical_return': None,
               'legs_hit': 1, 'legs_total': 1}
    summary = Ledger.summarize([unknown])
    assert summary['rate'] == 1 and summary['return_pending'] == 1
    assert summary['cost'] == '0' and summary['ret'] == '0.00'
    assert summary['roi'] is None
    known = unknown | {'theoretical_return': '3.60'}
    summary = Ledger.summarize([unknown, known])
    assert summary['settled'] == 2 and summary['hit'] == 2
    assert summary['cost'] == '2' and summary['ret'] == '3.60'
    assert summary['roi'] == 0.8 and summary['return_pending'] == 1
    losing = known | {'state': 'miss', 'theoretical_return': '0.00'}
    assert Ledger.summarize([losing])['roi'] == -1


def test_review_readable_tables_and_escaped_labels(workspace, ticket, football):
    from foot_web.services.drafts import render_draft
    _, config, source, _ = workspace
    ticket['title'] = '原票 | 方案'
    ticket['legs'][0]['options'][0].update(label='<script>alert(1)</script>|主胜', p_mkt=0.52)
    source.write_text(json.dumps(ticket, ensure_ascii=False) + '\n')
    result = ReviewService(config, fetcher=FakeFetcher({'football': [football]})).run('2026-11-04', 'tables')
    text = (Path(result['folder']) / 'review.md').read_text()
    assert text.index('最终推荐复盘汇总') < text.index('推荐命中率台账') < text.index('逐场结算')
    assert '| 模拟投入 | 理论返还 | 原票来源 |' in text
    assert '原票 &#124; 方案' in text
    assert '原选项与赔率' in text and '市场基准命中概率p_mkt（原票）' in text
    assert '0.52' in text and '3.60' in text and 'null' in text
    assert '<script>' not in text and '&amp;lt;script' not in text
    rendered = render_draft(text)
    assert rendered.count('<table>') >= 6 and '<script>' not in rendered


@pytest.mark.parametrize('compound', [False, True])
def test_review_shows_frozen_leg_probability_without_inventing_option_probabilities(workspace, ticket, football, compound):
    _, config, source, _ = workspace
    leg = ticket['legs'][0]
    leg['p_mkt'] = 0.654321
    if compound:
        leg['options'].append({'key': 'd', 'label': '平', 'odds': '3.20'})
    source.write_text(json.dumps(ticket, ensure_ascii=False) + '\n')
    result = ReviewService(config, fetcher=FakeFetcher({'football': [football]})).run('2026-11-04', 'leg-probability')
    text = (Path(result['folder']) / 'review.md').read_text()
    assert '本腿：0.654321' in text
    assert text.count('0.654321') == 1  # Compound union probability is not each option's probability.
    assert all('p_mkt' not in option for option in result['rows'][0]['settled_legs'][0]['options'])
    assert result['rows'][0]['settled_legs'][0]['p_mkt'] == leg['p_mkt']


def test_review_overlay_preserves_later_withdrawal_without_changing_settlement(tmp_path, ticket, football):
    from datetime import datetime
    from foot_web.storage.publications import PublicationsStore
    config = {'PROJECT_DIR': str(tmp_path), 'DATA_DIR': str(tmp_path / 'state')}
    store = PublicationsStore(config['DATA_DIR'])
    publication = {'id': 'publication-overlay', 'task_id': 'analysis-overlay', 'check_id': 'check-overlay',
                   'business_date': '2026-11-04', 'created_at': ticket['snapshot'],
                   'status': 'published', 'actor': 'admin1', 'previous_id': None}
    store.promote(publication, [ticket | {'publication_id': publication['id'], 'published_at': ticket['snapshot']}])
    result = ReviewService(config, fetcher=FakeFetcher({'football': [football]})).run('2026-11-04', 'review-overlay')
    folder = Path(result['folder'])
    frozen = {path.name: path.read_bytes() for path in folder.iterdir()}
    ledger = Ledger(tmp_path, config['DATA_DIR'])
    before = ledger.all()
    assert len(before) == 1 and before[0]['hit'] is True and not before[0]['withdrawn']
    store.withdraw(publication['id'], 'admin1', '撤销展示，原票仍结算', datetime.fromisoformat(ticket['snapshot']))
    after = ledger.all()
    assert len(after) == 1 and after[0]['withdrawn'] is True
    assert after[0]['withdrawal_reason'] == '撤销展示，原票仍结算'
    for field in ('ticket_id', 'hit', 'settled_legs', 'branches', 'sim_cost', 'theoretical_return'):
        assert after[0][field] == before[0][field]
    assert ledger.stats()['by_group']['最终推荐']['settled'] == 1
    assert frozen == {path.name: path.read_bytes() for path in folder.iterdir()}
