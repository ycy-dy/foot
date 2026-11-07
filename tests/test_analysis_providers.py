import json
import signal
import subprocess

import pytest

from foot_web.engine import providers

REPORT = '# 最终推荐汇总\n\n连通性测试，无赛事、无推荐、未审核未发布。'


def test_historical_cli_structured_response_parsing_and_errors():
    # Legacy artifacts remain parseable without enabling legacy runtime routing.
    claude = json.dumps({'type': 'result', 'is_error': False, 'structured_output': {'report_markdown': REPORT}})
    assert providers.parse_response('claude', claude).startswith('# 最终推荐汇总')
    assert providers.parse_response('codex', json.dumps({'report_markdown': REPORT})).startswith('# 最终推荐汇总')
    with pytest.raises(providers.ProviderError) as error:
        providers.parse_response('claude', json.dumps({'is_error': True, 'result': 'usage limit reached'}))
    assert error.value.code == 'rate_limit'
    for value in ('', '{}', 'not json', '{"report_markdown":"# 最终推荐汇总"}'):
        with pytest.raises(providers.ProviderError):
            providers.parse_response('codex', value)


def test_native_timeout_terminates_process_group(tmp_path, monkeypatch):
    killed = []

    class Process:
        pid = 12345
        returncode = -15
        calls = 0

        def communicate(self, input=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired('harness', timeout)

    monkeypatch.setattr(providers, 'executable', lambda *args: '/mock/tool')
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: Process())
    monkeypatch.setattr(providers.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    ticks = iter([0, 0, 901, 901])
    monkeypatch.setattr(providers.time, 'monotonic', lambda: next(ticks, 901))
    with pytest.raises(providers.ProviderError) as error:
        providers.generate('harness', 'test', tmp_path, {})
    assert error.value.code == 'timeout'
    assert killed == [(12345, signal.SIGTERM)]


def test_native_command_and_environment_are_restricted(tmp_path, monkeypatch):
    captured = {}

    class Process:
        pid = 12345
        returncode = 0

        def communicate(self, input=None, timeout=None):
            assert input == 'test prompt'

    def launch(args, **kwargs):
        captured.update(args=args, **kwargs)
        kwargs['stdout'].write(json.dumps({'type': 'final', 'text': json.dumps({'report_markdown': REPORT})}).encode())
        return Process()

    monkeypatch.setattr(providers, 'executable', lambda name, *args: '/mock/' + name)
    monkeypatch.setattr(subprocess, 'Popen', launch)
    monkeypatch.setattr(providers.os, 'killpg', lambda *args: None)
    monkeypatch.setenv('DINGTALK_CLIENT_SECRET', 'do-not-forward')
    monkeypatch.setenv('FOOT_SECRET_KEY', 'do-not-forward')
    project = tmp_path / 'project'
    project.mkdir()
    assert providers.generate('harness', 'test prompt', tmp_path, {'PROJECT_DIR': str(project)}).startswith('# 最终推荐汇总')
    assert captured['cwd'] == project.resolve()
    assert 'DINGTALK_CLIENT_SECRET' not in captured['env']
    assert 'FOOT_SECRET_KEY' not in captured['env']
    assert captured['start_new_session'] is True
    assert captured['args'][:3] == ['/mock/rtk', 'proxy', '/mock/harness']
    assert 'headless' in captured['args'] and '--json' in captured['args']
    assert captured['env']['DSH_PERMISSION_MODE'] == 'read-only'
