import math
import json
from pathlib import Path

from conftest import login


def test_probability_scores_use_only_settled_finite_original_probabilities():
    from foot_web.services.evaluation import score_forecasts
    samples = [
        {'key': 'a', 'p': .8, 'hit': True, 'matches': ['a']},
        {'key': 'b', 'p': .2, 'hit': False, 'matches': ['b']},
        {'key': 'c', 'p': .7, 'hit': None, 'matches': ['c']},
        {'key': 'd', 'p': None, 'hit': True, 'matches': ['d']},
        {'key': 'e', 'p': float('nan'), 'hit': False, 'matches': ['e']},
        {'key': 'f', 'p': 1.1, 'hit': True, 'matches': ['f']},
        {'key': 'a', 'p': .8, 'hit': True, 'matches': ['a']},
    ]
    result = score_forecasts(samples)
    assert result['records'] == 7 and result['duplicates'] == 1
    assert result['scored'] == 2 and result['pending'] == 1 and result['missing_probability'] == 3
    assert abs(result['brier'] - .04) < 1e-12
    assert abs(result['log_loss'] + math.log(.8)) < 1e-12
    assert result['hit_rate'] == .5 and result['mean_p_mkt'] == .5
    assert sum(row['n'] for row in result['bins']) == 2


def test_zero_probability_is_clipped_only_for_log_loss_and_empty_is_null():
    from foot_web.services.evaluation import score_forecasts
    assert score_forecasts([])['brier'] is None
    result = score_forecasts([{'key': 'zero', 'p': 0, 'hit': True, 'matches': ['m']}])
    assert result['brier'] == 1 and result['log_loss'] > 30
    assert result['clipped'] == 1


def test_leg_probability_never_inferred_from_ticket_result_or_later_prices():
    from foot_web.services.evaluation import forecast_rows
    record = {'business_date': '2026-11-04', 'kind': '足球最终串', 'title': '方案',
              'p_mkt': .4, 'hit': False,
              'legs': [{'sport': 'football', 'number': '周三001', 'market': 'HAD', 'p_mkt': .6,
                        'options': [{'key': 'h', 'odds': '1.50'}]},
                       {'sport': 'football', 'number': '周三002', 'market': 'HAD',
                        'options': [{'key': 'h', 'odds': '1.80'}]}]}
    rows = forecast_rows([record], unit='leg')
    assert len(rows) == 2 and all(row['hit'] is None for row in rows)
    assert rows[0]['p'] == .6 and rows[1]['p'] is None
    rows = forecast_rows([record])
    assert rows[0]['p'] == .4 and rows[0]['hit'] is False


def test_evaluation_page_is_authenticated_and_does_not_claim_model_deployment(client, identity):
    assert client.get('/research/evaluation').status_code == 302
    login(client, identity)
    response = client.get('/research/evaluation')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert '分析效果' in text and '独立模型未部署' in text
    assert '不补造事前概率' in text and '二元Brier' in text
    assert response.headers['Cache-Control'] == 'private, no-store'


def test_paired_comparison_retains_earlier_period_and_withdrawn_original(cfg, tmp_path, monkeypatch):
    from foot_web.services.evaluation import Evaluation, _baseline_ticket
    from foot_web.storage.publications import PublicationsStore
    from foot_web.services.research import moment
    root = tmp_path / 'project'
    config = cfg | {'PROJECT_DIR': str(root)}
    store = PublicationsStore(config['DATA_DIR'])

    def group(name, number, kickoff):
        leg = {'sport': 'football', 'num': number, 'matchup': '甲 VS 乙', 'home': '甲', 'away': '乙',
               'kickoff': kickoff, 'market': 'HAD', 'L': None, 'options': [{'key': 'h', 'odds': '1.80'}],
               'p_mkt': .6}
        return {'sport': 'football', 'name': name, 'legs': [leg, leg | {'num': number + 'b'}],
                'p_mkt_joint': .36}

    def save(key, time, groups):
        publication = {'id': key, 'task_id': key, 'check_id': key, 'business_date': '2026-11-04',
                       'created_at': time, 'actor': 'admin1', 'previous_id': None,
                       'status': 'published', 'manifest': {}}
        tickets = [_baseline_ticket(row, '2026-11-04') | {'published_at': time} for row in groups]
        store.promote(publication, tickets)
        folder = root / 'runs' / '2026-11-04' / key
        folder.mkdir(parents=True)
        (folder / 'tickets.json').write_text(json.dumps(tickets))
        (folder / 'audit.json').write_text(json.dumps({'source': {
            'as_of': time, 'football': [], 'basketball': [], 'fixture_groups': groups}}))

    early = group('足球早中场①', '001', '2026-11-04 18:00')
    late = group('足球晚场②', '003', '2026-11-05 02:00')
    save('publication-early', '2026-11-04T12:00:00+08:00', [early])
    save('publication-late', '2026-11-04T20:00:00+08:00', [late])
    store.withdraw('publication-late', 'admin1', '保留原始统计', moment('2026-11-04T21:00:00+08:00'))
    monkeypatch.setattr('foot_web.services.evaluation.build_bundle', lambda source, *a: {'groups': source['fixture_groups']})
    report = Evaluation(config, None, store).paired_comparison()
    assert report['matched_periods'] == report['baseline_available'] == report['ai_available'] == 2
    assert {row['period'] for row in report['rows']} == {'足球早中场①', '足球晚场②'}
    review_folder = root / 'runs' / '2026-11-04' / 'review-paired'
    review_folder.mkdir()
    (review_folder / 'results.json').write_text('{"football":[],"basketball":[]}')
    with store.store.connect() as db:
        db.execute('CREATE TABLE review_current(date TEXT PRIMARY KEY,run_id TEXT,payload TEXT)')
        db.execute('INSERT INTO review_current VALUES(?,?,?)', (
            '2026-11-04', 'review-paired', json.dumps({'run_id': 'review-paired'})))
    monkeypatch.setattr('foot_web.services.evaluation.settle', lambda ticket, results: ticket | {
        'hit': None if ticket.get('published_at') else True})
    pending = Evaluation(config, None, store).paired_comparison()
    assert pending['baseline']['scored'] == pending['ai']['scored'] == 0
    assert pending['baseline']['pending'] == pending['ai']['pending'] == 2
