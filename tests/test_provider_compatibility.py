import signal
import subprocess
import pytest
from foot_web.engine import providers


def test_code_modes_all_disabled_not_host_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, 'executable', lambda name, *a: '/mock/' + name)
    monkeypatch.setenv('CODEX_HOME', str(tmp_path))
    args = providers.command('codex', tmp_path, {})
    for feature in ('code_mode', 'code_mode_only', 'code_mode_prewarm', 'code_mode_host', 'shell_tool', 'unified_exec'):
        assert any(a == '--disable' and args[i+1] == feature for i, a in enumerate(args[:-1]))
    assert args[args.index('--enable') + 1] == 'standalone_web_search' and 'read-only' in args
    assert 'code_mode_host' not in [args[i+1] for i,x in enumerate(args[:-1]) if x == '--enable']


def test_configuration_error_classification():
    for text in ('Code Mode is unavailable because code-mode host is disabled.', 'unknown feature abc'):
        assert providers.failure(text).code == 'configuration'
    assert providers.failure('network failed').code == 'execution_failed'


def test_configuration_stream_fails_fast_and_cleans_group(tmp_path, monkeypatch):
    captured = {}
    killed = []
    class Process:
        pid = 12345
        returncode = None
        calls = 0
        def communicate(self, input=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                captured['stderr'].write(b'ERROR code-mode host is disabled\n')
                captured['stderr'].flush()
                raise subprocess.TimeoutExpired('codex', timeout)
            self.returncode = -15
    def launch(*args, **kwargs):
        captured.update(kwargs)
        return Process()
    monkeypatch.setattr(providers, 'command', lambda *a: ['mock'])
    monkeypatch.setattr(providers.subprocess, 'Popen', launch)
    monkeypatch.setattr(providers.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(providers.ProviderError) as err:
        providers.generate('codex', 'test', tmp_path, {}, schema={'type': 'object'})
    assert err.value.code == 'configuration'
    assert killed == [(12345, signal.SIGTERM)]
