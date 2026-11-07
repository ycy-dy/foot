import json
import os
import sys
import threading
from pathlib import Path

import pytest
from foot_web.services.versions import RULE_FILES

from conftest import ANALYSIS_ASOF, FakeFetcher, login
from foot_web.engine import providers
from foot_web.storage.db import Store

REPORT = '# 最终推荐汇总\n\n连通性测试，无赛事、无推荐。'


def test_native_stream_is_visible_before_cli_exit_and_keeps_failure(tmp_path, monkeypatch):
    received = threading.Event()
    release = tmp_path / 'release'
    script = tmp_path / 'cli.py'
    script.write_text(
        'import json, pathlib, sys, time\n'
        'sys.stdin.read()\n'
        'print(json.dumps({"type":"session","sessionId":"test"}), flush=True)\n'
        'print(json.dumps({"type":"tool_call","tool":"web_search"}), flush=True)\n'
        'while not pathlib.Path(sys.argv[1]).exists(): time.sleep(.02)\n'
        'print(json.dumps({"type":"error","message":"upstream timeout"}), flush=True)\n'
        'sys.exit(1)\n'
    )
    monkeypatch.setattr(providers, 'command', lambda *args: [sys.executable, str(script), str(release)])
    events, failures = [], []

    def on_event(kind, message):
        events.append((kind, message))
        if kind == 'tool':
            received.set()

    def run():
        try:
            providers.generate('harness', 'fixture', tmp_path, {}, on_event=on_event)
        except providers.ProviderError as exc:
            failures.append(exc.code)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert received.wait(4), 'CLI 退出前必须可见网页研究事件'
        assert thread.is_alive()
    finally:
        release.touch()
        thread.join(5)
    assert not thread.is_alive()
    assert failures == ['execution_failed']
    assert any('upstream timeout' in message for _, message in events)


def test_harness_jsonl_final_response_survives_stream_wrapping(tmp_path, monkeypatch):
    script = tmp_path / 'cli.py'
    final = json.dumps({'type': 'final', 'text': json.dumps({'report_markdown': REPORT})})
    script.write_text(
        'import sys\nsys.stdin.read()\n'
        'print(\'{"type":"session","sessionId":"fixture"}\', flush=True)\n'
        + 'print(' + repr(final) + ', flush=True)\n')
    monkeypatch.setattr(providers, 'command', lambda *args: [sys.executable, str(script)])
    events = []
    result = providers.generate('harness', 'fixture input', tmp_path, {}, on_event=lambda *row: events.append(row))
    assert result == REPORT + '\n'
    assert any('会话已启动' in text for _, text in events)
    assert any('最终结果' in text for _, text in events)


def test_native_timeout_keeps_prior_events_and_stops_process(tmp_path, monkeypatch):
    script = tmp_path / 'cli.py'
    pid_path = tmp_path / 'pid'
    script.write_text(
        'import os, pathlib, sys, time\n'
        'sys.stdin.read()\npathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n'
        'print(\'{"type":"session"}\', flush=True)\n'
        'time.sleep(60)\n')
    monkeypatch.setattr(providers, 'command', lambda *args: [sys.executable, str(script), str(pid_path)])
    events = []
    with pytest.raises(providers.ProviderError) as error:
        providers.generate('harness', 'fixture', tmp_path, {'FOOT_ANALYSIS_TIMEOUT': '10'},
                           on_event=lambda *row: events.append(row))
    assert error.value.code == 'timeout'
    assert any('会话已启动' in text for _, text in events)
    assert any('已停止 CLI 进程组' in text for _, text in events)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)


def test_valid_terminal_result_does_not_wait_for_cli_shutdown(tmp_path, monkeypatch):
    script = tmp_path / 'cli.py'
    pid_path = tmp_path / 'pid'
    script.write_text(
        'import os, pathlib, sys, json, time\n'
        'sys.stdin.read()\n'
        'pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n'
        'pathlib.Path(sys.argv[2]).write_text(json.dumps({"report_markdown":'
        + repr(REPORT) + '}))\n'
        'print(' + repr(json.dumps({'type': 'final', 'text': json.dumps({'report_markdown': REPORT})})) + ', flush=True)\n'
        'time.sleep(60)\n')
    monkeypatch.setattr(providers, 'command', lambda provider, folder, *a:
                        [sys.executable, str(script), str(pid_path), str(folder / 'response.json')])
    import time
    started = time.monotonic()
    assert providers.generate('harness', 'fixture', tmp_path, {'FOOT_ANALYSIS_TIMEOUT': '10'}) == REPORT + '\n'
    assert time.monotonic() - started < 4
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)


def test_harness_stream_keeps_public_evidence_and_never_private_reasoning():
    from foot_web.engine.logs import CLIEvents, redact
    seen = []
    stream = CLIEvents('harness', lambda kind, text: seen.append((kind, redact(text))))
    for event in [
        {'type': 'session', 'sessionId': 'fixture'},
        {'type': 'thinking', 'text': 'PRIVATE_REASONING'},
        {'type': 'user', 'text': 'PRIVATE_PROMPT'},
        {'type': 'text', 'text': '正在核对公开伤停来源'},
        {'type': 'tool_call', 'tool': 'web_search'},
        {'type': 'tool_result', 'result': '公开来源链接'},
        {'type': 'error', 'message': 'api_key=private-secret'},
    ]:
        stream.feed('stdout', json.dumps(event, ensure_ascii=False) + '\n')
    stream.finish()
    logged = json.dumps(seen, ensure_ascii=False)
    assert 'PRIVATE_' not in logged and 'private-secret' not in logged
    assert '公开伤停' in logged and 'web_search' in logged and '[REDACTED]' in logged
    assert stream.public_evidence == ['公开来源链接']


# Historical parser compatibility only: these fixtures never execute legacy CLIs.
@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_private_blocks_and_prompt_are_not_logged_but_public_events_are(tmp_path, provider):
    from foot_web.engine.logs import CLIEvents, redact

    seen = []
    stream = CLIEvents(provider, lambda kind, text: seen.append((kind, redact(text, ['test-secret-value']))))
    if provider == 'claude':
        events = [
            {'type': 'system', 'subtype': 'init', 'model': 'fixture'},
            {'type': 'assistant', 'message': {'content': [
                {'type': 'thinking', 'thinking': 'PRIVATE_REASONING'},
                {'type': 'text', 'text': '正在核对公开伤停来源'},
                {'type': 'tool_use', 'name': 'WebSearch', 'input': {'query': 'injury update'}},
            ]}},
            {'type': 'stream_event', 'event': {'type': 'content_block_delta',
                                             'delta': {'type': 'thinking_delta', 'thinking': 'PRIVATE_DELTA'}}},
            {'type': 'user', 'message': {'content': 'PRIVATE_PROMPT'}},
            {'type': 'result', 'is_error': True, 'result': 'Error: api_key=test-secret-value'},
        ]
    else:
        events = [
            {'type': 'thread.started', 'thread_id': 'fixture'},
            {'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'PRIVATE_REASONING'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '正在核对公开伤停来源'}},
            {'type': 'item.completed', 'item': {'type': 'web_search', 'action': {'query': 'injury update'}}},
            {'type': 'user', 'text': 'PRIVATE_PROMPT'},
            {'type': 'error', 'message': 'Error: api_key=test-secret-value'},
        ]
    for value in events:
        stream.feed('stdout', json.dumps(value, ensure_ascii=False) + '\n')
    stream.feed('stderr', 'Error: Authorization: Bearer another-secret-value\n')
    stream.finish()
    text = json.dumps(seen, ensure_ascii=False)
    assert 'PRIVATE_' not in text and 'test-secret-value' not in text and 'another-secret-value' not in text
    assert '公开伤停' in text and 'injury update' in text and '[REDACTED]' in text


def test_task_logs_are_incremental_persistent_and_admin_only(client, app, identity):
    tasks = app.extensions['analysis_tasks']
    task, _ = tasks.start('2026-11-04', 'admin1')
    store = Store(tasks.store.path)
    store.analysis_log(task['id'], 'harness', 'tool', 'WebSearch: official team news')
    store.analysis_log(task['id'], 'harness', 'output', '<script>alert("x")</script>')
    endpoint = task['logs_url']
    assert client.get(endpoint).status_code in (302, 401)
    login(client, identity, 'viewer1', '只读乙')
    assert client.get(endpoint).status_code == 403
    assert client.get(endpoint + '/download').status_code == 403
    with client.session_transaction() as session:
        csrf = session['csrf']
    client.post('/logout', data={'csrf': csrf})
    login(client, identity)
    response = client.get(endpoint + '?after=0&limit=1')
    assert response.status_code == 200
    assert 'no-store' in response.headers['Cache-Control']
    first = response.get_json()
    assert first['has_more'] is True and len(first['logs']) == 1
    second = client.get(endpoint + '?after=' + str(first['next_cursor'])).get_json()
    assert all(row['id'] > first['next_cursor'] for row in second['logs'])
    assert any('WebSearch' in row['message'] for row in first['logs'] + second['logs'])
    assert second['task']['id'] == task['id']
    assert client.get(endpoint + '?after=-1').status_code == 400
    assert client.get(endpoint + '?after=invalid').status_code == 400
    assert client.get(endpoint + '?after=0&limit=0').status_code == 400
    download = client.get(endpoint + '/download')
    assert download.status_code == 200
    assert download.mimetype == 'text/plain'
    assert 'attachment' in download.headers['Content-Disposition']
    assert b'official team news' in download.data
    assert client.get('/api/analysis/unknown/logs').status_code == 404
    html = client.get(task['result_url']).get_data(as_text=True)
    assert 'analysis-log-panel' in html and '跟随最新' in html
    assert '<script>alert("x")</script>' not in html


def test_logs_retention_is_bounded(tmp_path):
    store = Store(tmp_path / 'app.db')
    store.begin_analysis('run', '2026-11-04', 'admin1')
    for index in range(2005):
        store.analysis_log('run', 'harness', 'output', str(index) + 'x' * 5000)
    rows = store.analysis_logs('run', limit=2000)
    assert len(rows) == 2000
    assert rows[0]['message'].startswith('5x')
    assert max(len(row['message']) for row in rows) <= 4000


def test_harness_failure_logs_survive_without_cli_fallback(cfg, tmp_path, monkeypatch):
    from foot_web.engine import tasks as module

    project = tmp_path / 'project'
    project.mkdir()
    for name in RULE_FILES:
        (project / name).parent.mkdir(parents=True, exist_ok=True)
        (project / name).write_bytes((Path(cfg['PROJECT_DIR']) / name).read_bytes())
    config = cfg | {'PROJECT_DIR': str(project)}
    tasks = module.AnalysisTasks(config, launcher=lambda *args: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')

    def generate(provider, prompt, workspace, config, on_event=None, **kwargs):
        on_event('tool', 'WebSearch: public team update')
        on_event('error', 'Error: api_key=do-not-store-secret')
        raise providers.ProviderError('timeout', '本次 CLI 分析超时')

    monkeypatch.setattr(module, 'generate_report', generate)
    module.run_task(config, task['id'], fetcher=FakeFetcher(), as_of=ANALYSIS_ASOF)
    rows = tasks.store.analysis_logs(task['id'])
    assert 'harness' in {row['provider'] for row in rows}
    assert not ({row['provider'] for row in rows} & {'claude', 'codex'})
    assert not any('回退到' in row['message'] for row in rows)
    assert any(row['kind'] == 'error' and '超时' in row['message'] for row in rows)
    assert 'do-not-store-secret' not in json.dumps(rows)
    assert tasks.get(task['id'])['status'] == 'failed'
