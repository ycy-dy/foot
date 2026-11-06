import os
import shutil
import errno
import json
from pathlib import Path

import pytest

from conftest import ANALYSIS_ASOF, FakeFetcher, login, research_response
from foot_web import create_app


def test_recompute_starts_one_background_task_across_workers(cfg, identity):
    launched = []

    def launch(config, task_id):
        launched.append(task_id)
        return os.getpid()

    class NoRequestFetch:
        def get(self, *args, **kwargs):
            raise AssertionError('请求线程不应抓取数据')

    app = create_app(cfg, fetcher=NoRequestFetch(), identity=identity, analysis_launcher=launch)
    client = app.test_client()
    login(client, identity)
    with client.session_transaction() as session:
        csrf = session['csrf']
    response = client.post('/api/recompute', json={'date': '2026-11-04'}, headers={'X-CSRF': csrf})
    assert response.status_code == 202
    task = response.get_json()['task']
    assert task['status'] == 'queued'
    assert task['business_date'] == '2026-11-04'
    assert client.get(task['status_url']).get_json()['task']['id'] == task['id']

    other_app = create_app(cfg, fetcher=FakeFetcher(), identity=identity, analysis_launcher=launch)
    other_client = other_app.test_client()
    login(other_client, identity)
    with other_client.session_transaction() as session:
        csrf = session['csrf']
    repeated = other_client.post('/api/recompute', json={'date': '2026-11-04'}, headers={'X-CSRF': csrf})
    assert repeated.status_code == 202
    assert repeated.get_json()['task']['id'] == task['id']
    assert repeated.get_json()['reused'] is True
    assert launched == [task['id']]


@pytest.mark.parametrize('code', ['rate_limit', 'authentication', 'unavailable', 'timeout', 'invalid_output'])
def test_claude_failure_falls_back_to_codex_and_keeps_result_unpublished(cfg, tmp_path, code):
    from foot_web.engine.providers import ProviderError
    from foot_web.engine.tasks import AnalysisTasks, run_task

    root = Path(cfg['PROJECT_DIR'])
    project = tmp_path / 'project'
    project.mkdir()
    for name in ('AGENTS.md', 'analysis_recommendation_system_v6_0.md', 'analysis_recommendation_system_v6_0.yaml'):
        shutil.copy2(root / name, project / name)
    config = cfg | {'PROJECT_DIR': str(project)}
    tasks = AnalysisTasks(config, launcher=lambda config, task_id: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')
    called = []

    def generate(provider, prompt, workspace, config, **kwargs):
        called.append(provider)
        assert 'test-secret' not in prompt and 'DINGTALK_CLIENT_SECRET' not in prompt
        assert '市场基准' in prompt and '2026-11-04' in prompt
        if provider == 'claude':
            raise ProviderError(code, 'Claude 不可用')
        return research_response(prompt)

    run_task(config, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=ANALYSIS_ASOF)
    completed = tasks.get(task['id'])
    assert completed['status'] == 'succeeded' and completed['provider'] == 'codex'
    assert called[:2] == ['claude', 'codex']
    # Each completed match plus the mandatory final recommendation decision.
    assert called.count('codex') == completed['progress']['completed'] + 1
    assert completed['attempts'][0]['code'] == code
    folder = project / 'runs' / '2026-11-04' / task['id']
    assert (folder / 'report.draft.md').is_file()
    assert not (folder / 'report.md').exists()


def test_completed_task_is_not_overwritten_by_process_exit_race(cfg, monkeypatch):
    from foot_web.engine.tasks import AnalysisTasks

    tasks = AnalysisTasks(cfg, launcher=lambda config, task_id: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')

    def exited(pid, signal):
        tasks.store.update_analysis(task['id'], status='succeeded', message='已完成')
        raise ProcessLookupError(errno.ESRCH, 'process exited')

    monkeypatch.setattr(os, 'kill', exited)
    assert tasks.get(task['id'])['status'] == 'succeeded'


@pytest.fixture
def analysis_case(cfg, tmp_path):
    from foot_web.engine.tasks import AnalysisTasks

    project = tmp_path / 'project'
    project.mkdir()
    for name in ('AGENTS.md', 'analysis_recommendation_system_v6_0.md', 'analysis_recommendation_system_v6_0.yaml'):
        shutil.copy2(Path(cfg['PROJECT_DIR']) / name, project / name)
    config = cfg | {'PROJECT_DIR': str(project)}
    tasks = AnalysisTasks(config, launcher=lambda config, task_id: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')
    return config, tasks, task


def test_success_does_not_use_codex_and_running_same_job_twice_is_safe(analysis_case):
    from foot_web.engine.tasks import run_task
    from foot_web.services.reports import latest_report

    config, tasks, task = analysis_case
    called = []

    def generate(provider, prompt, *args, **kwargs):
        called.append(provider)
        return research_response(prompt)

    run_task(config, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=ANALYSIS_ASOF)
    run_task(config, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=ANALYSIS_ASOF)
    assert tasks.get(task['id'])['provider'] == 'claude'
    assert tasks.get(task['id'])['status'] == 'succeeded'
    assert set(called) == {'claude'} and len(called) == tasks.get(task['id'])['progress']['completed'] + 1
    assert latest_report(config['PROJECT_DIR'], '2026-11-04') is None


def test_both_providers_fail_without_success_or_report(analysis_case):
    from foot_web.engine.providers import ProviderError
    from foot_web.engine.tasks import run_task

    config, tasks, task = analysis_case

    def generate(*args, **kwargs):
        raise ProviderError('unavailable', '本机 CLI 无法启动')

    run_task(config, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=ANALYSIS_ASOF)
    completed = tasks.get(task['id'])
    assert completed['status'] == 'failed'
    assert [attempt['provider'] for attempt in completed['attempts']] == ['claude', 'codex']
    folder = Path(config['PROJECT_DIR']) / 'runs' / '2026-11-04' / task['id']
    assert not list(folder.glob('report*'))


def test_failed_timeout_cleanup_does_not_start_another_process(analysis_case):
    from foot_web.engine.providers import ProviderError
    from foot_web.engine.tasks import run_task

    config, tasks, task = analysis_case
    called = []

    def generate(provider, *args, **kwargs):
        called.append(provider)
        raise ProviderError('cleanup_failed', '无法清理超时进程，已停止自动回退')

    run_task(config, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=ANALYSIS_ASOF)
    assert tasks.get(task['id'])['status'] == 'failed'
    assert called == ['claude']


def test_task_api_permissions_and_invalid_dates(client, identity):
    login(client, identity, 'viewer1', '只读乙')
    assert client.get('/api/analysis/unknown').status_code == 403
    assert client.get('/analysis/unknown').status_code == 403
    with client.session_transaction() as session:
        csrf = session['csrf']
    client.post('/logout', data={'csrf': csrf})
    login(client, identity)
    assert client.get('/api/analysis/unknown').status_code == 404
    with client.session_transaction() as session:
        headers = {'X-CSRF': session['csrf']}
    for value in ('../../history', '2026-02-30', None, 123):
        assert client.post('/api/recompute', json={'date': value}, headers=headers).status_code == 400


def test_dead_worker_can_be_restarted(cfg, monkeypatch):
    from foot_web.engine.tasks import AnalysisTasks

    tasks = AnalysisTasks(cfg, launcher=lambda config, task_id: os.getpid())
    old, _ = tasks.start('2026-11-04', 'admin1')

    def missing(*args):
        raise ProcessLookupError(errno.ESRCH, 'missing')

    monkeypatch.setattr(os, 'kill', missing)
    assert tasks.get(old['id'])['status'] == 'interrupted'
    new, reused = tasks.start('2026-11-04', 'admin1')
    assert not reused and new['id'] != old['id']


def test_draft_is_accessible_to_admin_and_sanitized(analysis_case, identity):
    from foot_web.engine.tasks import run_task

    config, tasks, task = analysis_case

    def generate(provider, prompt, *args, **kwargs):
        payload = research_response(prompt)
        field = 'summary' if 'context_sha256' in payload else 'hypothesis'
        payload[field] = '<script>alert("x")</script><img src=x onerror=alert(1)> [unsafe](javascript:alert(1))'
        return payload

    run_task(config, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=ANALYSIS_ASOF)
    app = create_app(config, fetcher=FakeFetcher(), identity=identity, analysis_launcher=lambda *args: os.getpid())
    client = app.test_client()
    login(client, identity)
    response = client.get(tasks.get(task['id'])['result_url'])
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '未审核' in html and '未发布' in html
    assert '<script>alert' not in html and '<img src=x' not in html and 'href="javascript:' not in html
    assert client.get('/report?date=2026-11-04').status_code == 404
    assert '未发布 / 2026-11-04' in client.get('/?date=2026-11-04').get_data(as_text=True)


def test_simultaneous_requests_start_only_one_process(cfg):
    from concurrent.futures import ThreadPoolExecutor
    from foot_web.engine.tasks import AnalysisTasks

    launched = []

    def launch(config, task_id):
        launched.append(task_id)
        return os.getpid()

    def request(index):
        tasks = AnalysisTasks(cfg, launcher=launch)
        return tasks.start('2026-11-04', 'admin1')[0]['id']

    with ThreadPoolExecutor(max_workers=5) as pool:
        ids = list(pool.map(request, range(10)))
    assert len(set(ids)) == 1 and launched == [ids[0]]


def test_unavailable_inputs_never_start_an_agent(analysis_case):
    from foot_web.engine.tasks import run_task

    config, tasks, task = analysis_case

    class UnavailableFetcher:
        def get(self, *args, **kwargs):
            raise ValueError('official source unavailable')

    def generate(*args, **kwargs):
        raise AssertionError('不应使用缺失的数据调用模型')

    run_task(config, task['id'], fetcher=UnavailableFetcher(), generate=generate)
    assert tasks.get(task['id'])['status'] == 'failed'
    assert tasks.get(task['id'])['attempts'] == []
