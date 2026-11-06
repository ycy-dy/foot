import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from conftest import login
from foot_web.engine.review_tasks import ReviewTasks, run_review
from foot_web.scheduler import Scheduler
from foot_web.storage.jobs import JobsStore

TZ = ZoneInfo('Asia/Shanghai')
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=TZ)


@pytest.fixture
def jobs(cfg):
    return JobsStore(cfg['DATA_DIR'])


def save(jobs, **changes):
    return jobs.save_schedule({'name': '午间分析', 'kind': 'analysis', 'time': '12:01',
                               'offset': '0', 'enabled': '1'} | changes, 'admin1', NOW)


def test_schedule_defaults_validation_and_edit(jobs):
    assert jobs.schedules() == []
    row = save(jobs, enabled='0')
    assert not row['enabled'] and row['next_due'] is None
    row = save(jobs, id=str(row['id']))
    assert row['next_due'].startswith('2026-11-04T12:01')
    edited = save(jobs, id=str(row['id']), time='11:59')
    assert edited['next_due'].startswith('2026-11-05T11:59')
    for changes in ({'time': '25:00'}, {'offset': '-3'}, {'kind': 'shell'}, {'name': ''}, {'id': '999'}):
        with pytest.raises(ValueError):
            save(jobs, **changes)


def test_tick_deduplicates_workers_and_preserves_business_date(cfg, jobs):
    save(jobs, offset='-1')
    called = []

    class Tasks:
        def start(self, date, actor):
            called.append((date, actor))
            return {'id': 'task1', 'status': 'queued'}, False

    scheduler = Scheduler(cfg, Tasks(), Tasks(), jobs)
    due = NOW + timedelta(minutes=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: scheduler.tick(due), range(2)))
    assert called == [('2026-11-03', 'admin1')]
    assert jobs.fires()[0]['status'] == 'submitted'
    scheduler.tick(due + timedelta(seconds=20))
    assert len(called) == 1
    assert jobs.schedules()[0]['next_due'].startswith('2026-11-05')


def test_missed_busy_failed_and_revoked_are_honest(cfg, jobs):
    save(jobs)

    class Tasks:
        def start(self, *args):
            return {'id': 'other', 'status': 'running'}, True

    scheduler = Scheduler(cfg, Tasks(), Tasks(), jobs)
    scheduler.tick(NOW + timedelta(minutes=30))
    assert jobs.fires()[0]['status'] == 'skipped'
    assert '过期' in jobs.fires()[0]['message']
    scheduler.tick(NOW + timedelta(days=1, minutes=1))
    assert '繁忙' in jobs.fires()[0]['message']
    assert jobs.fires()[0]['task_id'] is None
    scheduler.config = cfg | {'FOOT_ADMIN_USER_IDS': ''}
    scheduler.tick(NOW + timedelta(days=2, minutes=1))
    assert '权限' in jobs.fires()[0]['message']


def test_recent_catchup_offline_days_and_disabled(jobs):
    save(jobs)
    claim = jobs.claim_due(NOW + timedelta(days=5, minutes=10))
    assert len(claim) == 1 and claim[0]['status'] == 'dispatching'
    assert claim[0]['business_date'] == '2026-11-09'
    # 离线五天不集中补跑五项。
    assert jobs.claim_due(NOW + timedelta(days=5, minutes=10)) == []
    row = jobs.schedules()[0]
    save(jobs, id=str(row['id']), enabled='0')
    assert jobs.claim_due(NOW + timedelta(days=10)) == []


def test_interrupted_dispatch_and_schedule_limit(jobs):
    save(jobs)
    fire = jobs.claim_due(NOW + timedelta(minutes=1))[0]
    jobs.claim_due(NOW + timedelta(minutes=3))
    assert jobs.fires()[0]['status'] == 'interrupted'
    jobs.finish_fire(fire['id'], 'submitted', 'too late', 'old')
    assert jobs.fires()[0]['status'] == 'interrupted'
    for i in range(11):
        save(jobs, name=str(i), enabled='0')
    with pytest.raises(ValueError, match='12'):
        save(jobs)


def test_dispatch_start_failure_is_recorded(cfg, jobs):
    save(jobs, kind='review')
    class Broken:
        def start(self, *args):
            raise OSError('failed')
    Scheduler(cfg, Broken(), Broken(), jobs).tick(NOW + timedelta(minutes=1))
    assert jobs.fires()[0]['status'] == 'failed'


def test_review_launch_failure_and_dead_worker(cfg, jobs, monkeypatch):
    import errno
    def broken(*args):
        raise OSError('failed')
    tasks = ReviewTasks(cfg, jobs, launcher=broken)
    task, reused = tasks.start('2026-11-03', 'admin1')
    assert task['status'] == 'failed' and not reused
    tasks.launcher = lambda *_: 1234567
    task, _ = tasks.start('2026-11-04', 'admin1')
    def missing(pid, signal):
        raise ProcessLookupError(errno.ESRCH, 'gone')
    monkeypatch.setattr(os, 'kill', missing)
    assert tasks.get(task['id'])['status'] == 'interrupted'


def test_review_task_dedup_worker_and_failure(cfg, jobs):
    tasks = ReviewTasks(cfg, jobs, launcher=lambda *_: os.getpid())
    task, reused = tasks.start('2026-11-03', 'admin1')
    assert not reused
    assert tasks.start('2026-11-04', 'admin1')[1]

    class Service:
        def run(self, business_date, run_id):
            assert business_date == '2026-11-03'
            return {'rows': []}

    run_review(cfg, task['id'], service=Service())
    assert tasks.get(task['id'])['status'] == 'succeeded'
    assert not tasks.start('2026-11-04', 'admin1')[1]
    second = tasks.latest()[0]

    class Broken:
        def run(self, *args):
            raise ValueError('没有可复盘的冻结原票')

    run_review(cfg, second['id'], service=Broken())
    assert tasks.get(second['id'])['status'] == 'failed'
    assert '冻结原票' in tasks.get(second['id'])['message']
    with pytest.raises(ValueError):
        tasks.start('../oops', 'admin1')


def test_review_worker_subprocess_no_tickets_is_explicit(cfg, tmp_path):
    import subprocess
    import sys
    project = tmp_path / 'empty-project'
    project.mkdir()
    config = cfg | {'PROJECT_DIR': str(project)}
    jobs = JobsStore(config['DATA_DIR'])
    jobs.begin_review('review-subprocess-test', '2026-11-03', 'admin1')
    # 没有原票时应在任何外部抓取前失败；真实执行独立入口，不接触生产数据库。
    result = subprocess.run([sys.executable, '-m', 'foot_web.engine.review_worker',
                             '--task-id', 'review-subprocess-test', '--project-dir', str(project),
                             '--data-dir', config['DATA_DIR']], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    task = jobs.review('review-subprocess-test')
    assert task['status'] == 'failed' and '冻结原票' in task['message']
    assert 'RuntimeWarning' not in result.stderr


def test_automation_routes_permissions_csrf_and_forms(client, identity, app):
    assert app.extensions['scheduler']._thread is None
    assert app.extensions['jobs'].schedules() == []
    assert client.get('/automation').status_code == 302
    login(client, identity, 'viewer1')
    assert client.get('/automation').status_code == 403
    assert client.get('/reviews').status_code == 200
    assert client.post('/reviews', data={}).status_code == 403
    login(client, identity)
    assert client.get('/automation').status_code == 200
    assert client.post('/automation', data={}).status_code == 400
    with client.session_transaction() as session:
        csrf = session['csrf']
    response = client.post('/automation', data={'csrf': csrf, 'name': '测试', 'kind': 'analysis',
                                               'time': '12:00', 'offset': '0'})
    assert response.status_code == 303
    assert '测试' in client.get('/automation').get_data(as_text=True)
    assert client.post('/reviews', data={'csrf': csrf, 'date': 'bad'}).status_code == 400
    app.extensions['review_tasks'].launcher = lambda *_: os.getpid()
    response = client.post('/reviews', data={'csrf': csrf, 'date': '2026-11-03'})
    assert response.status_code == 303
    assert '/reviews/review-' in response.location
    assert client.get(response.location).status_code == 200
    assert client.get('/api/reviews/unknown').status_code == 404
