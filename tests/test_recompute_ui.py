from test_ui import Elements
from conftest import login


def test_admin_dashboard_wires_analysis_controller_and_button(client, identity):
    login(client, identity)
    html = client.get('/?date=2026-11-04').get_data(as_text=True)
    doc = Elements(html)
    button = doc.with_attr('id', 'btn-recompute')[0][1]
    assert button['type'] == 'button' and button['data-analysis-date'] == '2026-11-04'
    assert '<span>重新分析</span>' in html
    assert doc.with_attr('id', 'analysis-task-data')
    assert len([a for _, a in doc.with_attr('src') if '/static/analysis.js?' in a['src']]) == 1
    assert doc.with_attr('id', 'analysis-status') and doc.with_attr('id', 'analysis-message')


def test_viewer_has_no_submission_controller(client, identity):
    login(client, identity, user_id='viewer1')
    doc = Elements(client.get('/?date=2026-11-04').get_data(as_text=True))
    assert not doc.with_attr('id', 'btn-recompute')
    assert not any('/static/analysis.js?' in a['src'] for _, a in doc.with_attr('src'))


def test_button_api_creates_one_job_and_reports_reused(client, identity, app, monkeypatch):
    login(client, identity)
    launched = []
    monkeypatch.setattr(app.extensions['analysis_tasks'], 'launcher', lambda *args: launched.append(args) or __import__('os').getpid())
    with client.session_transaction() as session:
        csrf = session['csrf']
    responses = [client.post('/api/recompute', json={'date': '2026-11-04'}, headers={'X-CSRF': csrf}) for _ in range(2)]
    assert all(r.status_code == 202 for r in responses)
    assert responses[0].json['reused'] is False and responses[1].json['reused'] is True
    assert responses[0].json['task']['id'] == responses[1].json['task']['id']
    assert len(launched) == 1
