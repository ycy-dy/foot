from test_ui import Elements
from conftest import login
import os
import errno
import pytest


def test_admin_dashboard_wires_analysis_controller_and_button(client, identity):
    login(client, identity)
    html = client.get('/?date=2026-11-04').get_data(as_text=True)
    doc = Elements(html)
    button = doc.with_attr('id', 'btn-recompute')[0][1]
    assert button['type'] == 'button' and button['data-analysis-date'] == '2026-11-04'
    assert '<span>开始分析</span>' in html
    assert doc.with_attr('id', 'analysis-task-data')
    assert len([a for _, a in doc.with_attr('src') if '/static/analysis.js?' in a['src']]) == 1
    assert doc.with_attr('id', 'analysis-status') and doc.with_attr('id', 'analysis-message')


def test_other_business_day_task_does_not_make_today_a_reanalysis(client, identity, app):
    login(client, identity)
    tasks = app.extensions['analysis_tasks']
    tasks.launcher = lambda *args: os.getpid()
    tasks.start('2026-11-08', 'admin1')
    html = client.get('/?date=2026-11-04').get_data(as_text=True)
    assert '<span>开始分析</span>' in html
    assert 'id="analysis-task-data">null</script>' in html


@pytest.mark.parametrize('status,attempted,expected', [
    ('queued', False, '等待分析'), ('running', False, 'Codex CLI分析中'),
    ('succeeded', True, '重新分析'), ('partial', True, '重新分析'),
    ('failed', True, '重新分析'), ('cancelled', True, '重新分析'),
    ('interrupted', True, '重新分析'), ('cancelled', False, '开始分析'),
    ('failed', False, '重试分析'), ('interrupted', False, '重试分析'),
])
def test_same_day_action_matches_saved_execution_state(client, identity, app, status, attempted, expected):
    login(client, identity)
    tasks = app.extensions['analysis_tasks']
    task, _ = tasks.start('2026-11-04', 'admin1')
    tasks.store.update_analysis(task['id'], status=status, provider='codex',
                                attempts=[{'provider': 'codex', 'status': 'failed', 'code': 'timeout'}] if attempted else [])
    html = client.get('/?date=2026-11-04').get_data(as_text=True)
    button = Elements(html).with_attr('id', 'btn-recompute')[0][1]
    assert f'<span>{expected}</span>' in html
    assert ('disabled' in button) == (status in ('queued', 'running'))
    api = client.get(task['status_url']).json['task']
    assert api['action']['label'] == expected


def test_cross_day_start_returns_explicit_busy_without_switching_task(client, identity, app):
    login(client, identity)
    tasks = app.extensions['analysis_tasks']
    task, _ = tasks.start('2026-11-08', 'admin1')
    with client.session_transaction() as session:
        csrf = session['csrf']
    response = client.post('/api/recompute', json={'date': '2026-11-09'}, headers={'X-CSRF': csrf})
    assert response.status_code == 409 and response.json['success'] is False
    assert response.json['busy_task']['id'] == task['id']
    assert '2026-11-08' in response.json['message']
    assert tasks.latest('2026-11-09') is None
    tasks.cancel(task['id'], 'admin1')
    response = client.post('/api/recompute', json={'date': '2026-11-09'}, headers={'X-CSRF': csrf})
    assert response.status_code == 202 and response.json['task']['business_date'] == '2026-11-09'


def test_cancelled_new_queue_keeps_same_day_prior_analysis_history(app):
    tasks = app.extensions['analysis_tasks']
    old, _ = tasks.start('2026-11-04', 'admin1')
    tasks.store.update_analysis(old['id'], status='failed', attempts=[{'status': 'failed', 'provider': 'codex', 'code': 'timeout'}])
    new, _ = tasks.start('2026-11-04', 'admin1')
    cancelled = tasks.cancel(new['id'], 'admin1')
    assert cancelled['action']['label'] == '重新分析'
    assert cancelled['has_analysis_history'] is True
    assert tasks.latest('2026-11-09') is None


def test_dead_cross_day_worker_is_recovered_before_starting_new_day(app, monkeypatch):
    tasks = app.extensions['analysis_tasks']
    old, _ = tasks.start('2026-11-08', 'admin1')

    def missing(*args):
        raise ProcessLookupError(errno.ESRCH, 'isolated dead worker')

    monkeypatch.setattr(os, 'kill', missing)
    new, reused = tasks.start('2026-11-09', 'admin1')
    assert not reused and new['business_date'] == '2026-11-09'
    assert tasks.store.analysis(old['id'])['status'] == 'interrupted'


def test_cross_task_resume_returns_busy_not_false_success(client, identity, app):
    from foot_web.services.versions import rules_manifest
    login(client, identity)
    tasks = app.extensions['analysis_tasks']
    old, _ = tasks.start('2026-11-04', 'admin1')
    manifest, _ = rules_manifest(app.config['FOOT']['PROJECT_DIR'])
    tasks.research.initialize(old['id'], manifest, {}, [])
    tasks.store.update_analysis(old['id'], status='partial')
    active, _ = tasks.start('2026-11-09', 'admin1')
    with client.session_transaction() as session:
        csrf = session['csrf']
    response = client.post(f'/api/analysis/{old["id"]}/resume', headers={'X-CSRF': csrf})
    assert response.status_code == 409 and not response.json['success']
    assert '2026-11-09' in response.json['message']
    assert tasks.get(old['id'])['status'] == 'partial'
    assert tasks.get(active['id'])['status'] == 'queued'


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
