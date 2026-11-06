import json
import signal
import subprocess
import tomllib

import pytest

from foot_web.engine import providers

REPORT = '# 最终推荐汇总\n\n连通性测试，无赛事、无推荐、未审核未发布。'


def test_native_structured_responses_and_errors():
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
                raise subprocess.TimeoutExpired('claude', timeout)

    monkeypatch.setattr(providers, 'executable', lambda *args: '/mock/tool')
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: Process())
    monkeypatch.setattr(providers.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    ticks = iter([0, 0, 901, 901])
    monkeypatch.setattr(providers.time, 'monotonic', lambda: next(ticks, 901))
    with pytest.raises(providers.ProviderError) as error:
        providers.generate('claude', 'test', tmp_path, {})
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
        kwargs['stdout'].write(json.dumps({'structured_output': {'report_markdown': REPORT}}).encode())
        return Process()

    monkeypatch.setattr(providers, 'executable', lambda name, *args: '/mock/' + name)
    monkeypatch.setattr(subprocess, 'Popen', launch)
    monkeypatch.setattr(providers.os, 'killpg', lambda *args: None)
    monkeypatch.setenv('DINGTALK_CLIENT_SECRET', 'do-not-forward')
    monkeypatch.setenv('FOOT_SECRET_KEY', 'do-not-forward')
    project = tmp_path / 'project'
    project.mkdir()
    assert providers.generate('claude', 'test prompt', tmp_path, {'PROJECT_DIR': str(project)}).startswith('# 最终推荐汇总')
    assert captured['cwd'] == project.resolve()
    assert 'DINGTALK_CLIENT_SECRET' not in captured['env']
    assert 'FOOT_SECRET_KEY' not in captured['env']
    assert captured['start_new_session'] is True
    assert '--setting-sources' in captured['args'] and '--tools' in captured['args']
    assert '{"disableAllHooks":true}' in captured['args']
    assert '--safe-mode' not in captured['args']
    assert not any('dangerously' in value for value in captured['args'])

    monkeypatch.setenv('CODEX_HOME', str(tmp_path))
    (tmp_path / 'config.toml').write_text(
        '[mcp_servers.test]\ncommand="unused"\n[mcp_servers."desktop.plugin"]\ncommand="unused"\n')
    args = providers.command('codex', tmp_path, {})
    assert args[:3] == ['/mock/rtk', 'proxy', '/mock/codex']
    assert 'read-only' in args and '--output-schema' in args
    assert 'mcp_servers={}' in args
    override = next(value for value in args if value.startswith('mcp_servers={') and value != 'mcp_servers={}')
    assert tomllib.loads(override) == {'mcp_servers': {
        'test': {'enabled': False, 'command': '/usr/bin/false', 'args': []},
        'desktop.plugin': {'enabled': False, 'command': '/usr/bin/false', 'args': []}}}
    assert 'unused' not in ' '.join(args)
    assert not any(value.startswith('mcp_servers.') for value in args)
    assert 'shell_tool' in args and 'hooks' in args
    assert not any('dangerously' in value for value in args)
