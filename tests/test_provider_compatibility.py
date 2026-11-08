import json
import signal
import subprocess
import pytest
from foot_web.engine import providers


def test_harness_command_uses_isolated_headless_patch(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, 'executable', lambda name, *a: '/mock/' + name)
    args = providers.command('harness', tmp_path, {})
    assert args[:4] == ['/mock/rtk', 'proxy', '/mock/harness', 'headless']
    assert '--patch' in args and args[-2:] == ['--json', '-']
    assert 'claude' not in ' '.join(args) and 'codex' not in ' '.join(args)


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
                captured['stderr'].write(b'ERROR unknown feature unavailable_feature\n')
                captured['stderr'].flush()
                raise subprocess.TimeoutExpired('harness', timeout)
            self.returncode = -15
    def launch(*args, **kwargs):
        captured.update(kwargs)
        return Process()
    monkeypatch.setattr(providers, 'command', lambda *a: ['mock'])
    monkeypatch.setattr(providers.subprocess, 'Popen', launch)
    monkeypatch.setattr(providers.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(providers.ProviderError) as err:
        providers.generate('harness', 'test', tmp_path, {}, schema={'type': 'object'})
    assert err.value.code == 'configuration'
    assert killed == [(12345, signal.SIGTERM)]


@pytest.mark.parametrize('diagnostic', [
    'Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed;',
    '2026-11-08T02:58:06Z ERROR codex_core::tools::router: error=code-mode host is disabled',
])
def test_optional_host_diagnostic_does_not_kill_native_web_success(tmp_path, monkeypatch, diagnostic):
    captured, events, killed = {}, [], []

    class Process:
        pid = 12345
        returncode = None
        calls = 0

        def communicate(self, input=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                captured['stderr'].write((diagnostic + '\n').encode())
                captured['stderr'].flush()
                raise subprocess.TimeoutExpired('codex', timeout)
            self.returncode = 0
            payloads = [
                {'type': 'item.completed', 'item': {
                    'id': 'web-1', 'type': 'web_search', 'action': {'type': 'search'}}},
                {'type': 'turn.completed', 'usage': {'output_tokens': 20}},
            ]
            captured['stdout'].write(('\n'.join(json.dumps(p) for p in payloads) + '\n').encode())
            captured['stdout'].flush()
            (tmp_path / 'codex/response.json').write_text('{"ok":true}')

    def launch(*args, **kwargs):
        captured.update(kwargs)
        return Process()

    monkeypatch.setattr(providers, 'command', lambda *a: ['fake-codex'])
    monkeypatch.setattr(providers.subprocess, 'Popen', launch)
    monkeypatch.setattr(providers.os, 'killpg', lambda pid, sig: killed.append(pid))
    result = providers.generate('codex', 'test', tmp_path, {}, schema={'type': 'object'},
                                on_event=lambda kind, text: events.append((kind, text)))
    assert result == {'ok': True}
    assert not killed
    assert any(kind == 'warning' and 'code-mode' in text for kind, text in events)
    assert any(kind == 'tool' and 'WebSearch' in text for kind, text in events)


def test_terminal_host_failure_is_not_hidden_by_a_response_file(tmp_path, monkeypatch):
    killed = []

    class Process:
        pid = 12345
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return None

    def launch(*args, **kwargs):
        event = {'type': 'turn.failed', 'error': {'message': 'code-mode host is disabled'}}
        kwargs['stdout'].write((json.dumps(event) + '\n').encode())
        kwargs['stdout'].flush()
        (tmp_path / 'codex/response.json').write_text('{"ok":true}')
        return Process()

    monkeypatch.setattr(providers, 'command', lambda *a: ['fake-codex'])
    monkeypatch.setattr(providers.subprocess, 'Popen', launch)
    monkeypatch.setattr(providers.os, 'killpg', lambda pid, sig: killed.append(pid))
    with pytest.raises(providers.ProviderError) as error:
        providers.generate('codex', 'test', tmp_path, {}, schema={'type': 'object'})
    assert error.value.code == 'configuration'


def test_codex_command_retains_research_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, 'executable', lambda name, *a: '/mock/' + name)
    monkeypatch.setattr(providers, 'direct_model_catalog', lambda binary: '{"models":[{"slug":"same-model","tool_mode":"direct"}]}')
    args = providers.command('codex', tmp_path, {})
    disabled = {args[i + 1] for i, value in enumerate(args) if value == '--disable'}
    assert {'code_mode', 'code_mode_host', 'shell_tool', 'unified_exec', 'multi_agent',
            'plugins', 'hooks'}.issubset(disabled)
    assert args[args.index('--sandbox') + 1] == 'read-only'
    assert 'standalone_web_search' in args
    assert any('只使用原生' in value for value in args)
    assert json.loads((tmp_path / 'direct-model-catalog.json').read_text())['models'][0]['tool_mode'] == 'direct'


def test_direct_catalog_preserves_model_identity_and_other_metadata(monkeypatch):
    providers.direct_model_catalog.cache_clear()
    original = {'models': [{'slug': 'existing-model', 'tool_mode': 'code_mode_only',
                             'base_instructions': 'original instructions', 'context_window': 1000}]}
    monkeypatch.setattr(providers, 'executable', lambda *a: '/mock/rtk')
    captured = []
    def run(args, **kwargs):
        captured.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(original).encode())
    monkeypatch.setattr(providers.subprocess, 'run', run)
    catalog = json.loads(providers.direct_model_catalog('/mock/codex'))
    assert catalog['models'][0] == original['models'][0] | {'tool_mode': 'direct', 'supports_search_tool': False}
    assert captured[0][0][-2:] == ['debug', 'models']
    assert captured[0][1]['timeout'] == 10
    providers.direct_model_catalog.cache_clear()


@pytest.mark.parametrize('message', [
    'Code Mode is unavailable because code-mode host is disabled.',
    'Codex is ignoring 3 unrecognized configuration settings.',
    'Under-development features enabled: standalone_web_search.',
])
def test_nonterminal_diagnostics_are_warnings_but_terminal_is_error(message):
    from foot_web.engine.logs import CLIEvents
    events = []
    stream = CLIEvents('codex', lambda kind, text: events.append((kind, text)))
    stream.codex({'type': 'item.completed', 'item': {'type': 'error', 'message': message}})
    assert events[-1] == ('warning', message)
    assert stream.terminal_error is None
    stream.codex({'type': 'error', 'message': message})
    assert stream.terminal_error == message
    stream.codex({'type': 'turn.failed', 'error': {'message': message}})
    assert stream.terminal_error == message
    assert events[-1] == ('error', message)
