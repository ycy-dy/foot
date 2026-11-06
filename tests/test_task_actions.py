"""Task controls use isolated state and actual review boundaries with mocked external responses."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from foot_web.services.versions import RULE_FILES

from conftest import FakeFetcher, login
from foot_web import create_app
from foot_web.engine.review_tasks import run_review
from test_ai_decisions import response as review_response
from test_ui import Elements


@pytest.fixture
def actions(cfg, tmp_path, identity):
    root = tmp_path / 'project'
    root.mkdir()
    for name in RULE_FILES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes((Path(cfg['PROJECT_DIR']) / name).read_bytes())
    folder = root / 'ledger' / 'data'
    folder.mkdir(parents=True)
    tickets = []
    for day, number in [('2026-11-03', '周二001'), ('2026-11-04', '周三001')]:
        tickets.append({'business_date': day, 'kind': '足球单场方向', 'title': '冻结单场方向',
                        'ledger': 'rec', 'source_file': 'original-report.md',
                        'snapshot': day + 'T12:00:00+08:00', 'hit': None, 'actual_stake': None,
                        'actual_return': None, 'legs': [{'sport': 'football', 'number': number,
                        'match_date': day, 'matchup': '主队 VS 客队', 'market': 'HAD', 'goal_line': '',
                        'options': [{'key': 'h', 'label': '主胜', 'odds': '1.80'}]}]})
    frozen = folder / 'records_actions.jsonl'
    frozen.write_text('\n'.join(json.dumps(row) for row in tickets) + '\n')
    (folder / 'settled_records.json').write_text(json.dumps(tickets))
    config = cfg | {'PROJECT_DIR': str(root), 'DATA_DIR': str(tmp_path / 'var')}
    app = create_app(config, fetcher=FakeFetcher(), identity=identity,
                     analysis_launcher=lambda *a: os.getpid())
    app.extensions['review_tasks'].launcher = lambda *a: os.getpid()
    return app, app.test_client(), config, frozen


def test_stop_is_in_header_and_uses_existing_csrf_control(actions, identity):
    app, client, _, _ = actions
    login(client, identity)
    task, _ = app.extensions['analysis_tasks'].start('2026-11-04', 'admin1')
    html = client.get('/?date=2026-11-04').get_data(as_text=True)
    page = Elements(html)
    stop = page.with_attr('id', 'btn-analysis-stop')[0][1]
    assert 'hidden' not in stop and stop['data-analysis-action'] == 'cancel'
    assert html.index('id="btn-analysis-stop"') < html.index('id="analysis-workspace"')
    assert len(page.with_attr('data-analysis-action', 'cancel')) == 2
    assert client.post(f'/api/analysis/{task["id"]}/cancel', json={}).status_code == 400
    with client.session_transaction() as session:
        csrf = session['csrf']
    stopped = client.post(f'/api/analysis/{task["id"]}/cancel', json={}, headers={'X-CSRF': csrf})
    assert stopped.status_code == 200 and stopped.json['task']['status'] == 'cancelled'
    html = client.get('/?date=2026-11-04').get_data(as_text=True)
    assert 'hidden' in Elements(html).with_attr('id', 'btn-analysis-stop')[0][1]
    login(client, identity, 'viewer1')
    assert not Elements(client.get('/').get_data(as_text=True)).with_attr('id', 'btn-analysis-stop')


def test_history_review_updates_only_selected_day_and_preserves_original(actions, identity, monkeypatch):
    from foot_web.data.results import ResultsFetcher
    from foot_web.engine import decisions
    app, client, config, frozen = actions
    login(client, identity)
    original = hashlib.sha256(frozen.read_bytes()).hexdigest()
    html = client.get('/history?date=2026-11-04').get_data(as_text=True)
    assert Elements(html).with_attr('id', 'history-review-form')
    assert '复盘并更新结果' in html and 'value="2026-11-04"' in html
    assert client.post('/reviews', data={'date': '2026-11-04', 'origin': 'history'}).status_code == 400
    with client.session_transaction() as session:
        csrf = session['csrf']
    data = {'csrf': csrf, 'date': '2026-11-04', 'origin': 'history'}
    requested = client.post('/reviews', data=data)
    assert requested.status_code == 303 and requested.location.endswith('/history?date=2026-11-04')
    client.post('/reviews', data=data)
    tasks = app.extensions['review_tasks'].latest()
    assert len(tasks) == 1 and tasks[0]['business_date'] == '2026-11-04'
    progress = client.get(requested.location).get_data(as_text=True)
    assert '查看复盘进度' in progress and 'data-refresh-on-finish="true"' in progress
    results = {'football': [{'matchNumStr': '周三001', 'matchDate': '2026-11-04',
                            'allHomeTeam': '主队', 'allAwayTeam': '客队',
                            'matchResultStatus': '2', 'sectionsNo999': '2:1', 'sectionsNo1': '1:0'}],
               'basketball': [], 'sources': []}
    monkeypatch.setattr(ResultsFetcher, 'fetch', lambda *a, **kw: copy.deepcopy(results))
    monkeypatch.setattr(decisions, 'generate', lambda provider, prompt, *a, **kw:
                        review_response(json.loads(prompt.split('=== FROZEN REVIEW DATA ===\n')[1])['rows']))
    run_review(config, tasks[0]['id'])
    assert app.extensions['review_tasks'].get(tasks[0]['id'])['status'] == 'succeeded'
    updated = client.get(requested.location).get_data(as_text=True)
    assert '已更新结果' in updated and 'data-has-report="true"' in updated
    ledger = app.extensions['ledger']
    assert ledger.query(date_from='2026-11-04', date_to='2026-11-04')[0]['hit'] is True
    assert ledger.query(date_from='2026-11-03', date_to='2026-11-03')[0]['hit'] is None
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == original
    assert all(row['actual_stake'] is None and row['actual_return'] is None for row in ledger.all())
    login(client, identity, 'viewer1')
    assert not Elements(client.get(requested.location).get_data(as_text=True)).with_attr('id', 'history-review-form')
    assert client.post('/reviews', data=data).status_code == 403


def test_empty_history_does_not_offer_review(actions, identity):
    _, client, _, _ = actions
    login(client, identity)
    page = Elements(client.get('/history?date=2026-11-02').get_data(as_text=True))
    assert not page.with_attr('id', 'history-review-form')
