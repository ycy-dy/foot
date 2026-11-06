from datetime import datetime
from zoneinfo import ZoneInfo

from conftest import FakeFetcher, login, research_payload
from foot_web.data.markets import parse_football
from foot_web.services.research import match_key
from foot_web.services.versions import rules_manifest
from foot_web.services.match_analysis import latest_match_analysis


def fixture_item(app):
    tasks = app.extensions['analysis_tasks']
    match = parse_football(FakeFetcher().data['football'])[0]
    task, _ = tasks.store.begin_analysis('per-match-test', match['business_date'], 'admin1')
    manifest, _ = rules_manifest(app.config['FOOT']['PROJECT_DIR'])
    tasks.research.initialize(task['id'], manifest, {'business_date': match['business_date']},
                              [{'match': match, 'match_key': match_key(match)}])
    tasks.research.update_item(task['id'], match_key(match), status='succeeded',
                              message='模拟研究已完成', payload=research_payload(match),
                              as_of='2026-11-04T12:00:00+08:00')
    return tasks, match


def test_dashboard_has_per_match_link_and_empty_state(client, identity):
    login(client, identity)
    text = client.get('/?date=2026-11-04').get_data(as_text=True)
    assert '逐场分析</a>' in text
    assert '/match/football/' in text


def test_projection_exact_identity_and_low_quality(app):
    tasks, match = fixture_item(app)
    asof = datetime(2026, 11, 4, 12, tzinfo=ZoneInfo('Asia/Shanghai'))
    row = latest_match_analysis(tasks, match, app.config['FOOT'], asof)
    assert row['status'] == 'succeeded' and row['current_version']
    assert row['evidence'] and row['options']
    assert not any((o['evidence_confidence'] or {}).get('eligible') for o in row['options'])
    assert latest_match_analysis(tasks, match | {'home': 'another team'}, app.config['FOOT'], asof) is None
    assert latest_match_analysis(tasks, match | {'business_date': '2026-11-05'}, app.config['FOOT'], asof) is None


def test_viewer_reads_summary_but_not_admin_evidence(app, client, identity):
    tasks, match = fixture_item(app)
    login(client, identity, user_id='viewer1')
    path = f'/match/football/{match["num"]}?date={match["business_date"]}'
    response = client.get(path)
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert '逐场 AI 分析' in text and '不推荐' in text
    assert '研究任务与日志' not in text
    assert client.get(f'/analysis/per-match-test/matches/{match_key(match)}').status_code == 403


def test_match_without_research_has_no_fabricated_result(client, identity):
    login(client, identity)
    match = parse_football(FakeFetcher().data['football'])[0]
    text = client.get(f'/match/football/{match["num"]}?date={match["business_date"]}').get_data(as_text=True)
    assert '待分析' in text and '不会用赔率或模板补造AI结论' in text
