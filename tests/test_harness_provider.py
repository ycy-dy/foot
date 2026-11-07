import json
from pathlib import Path
import pytest
from foot_web.engine import providers
from foot_web.engine.logs import CLIEvents


def test_harness_command_has_only_official_headless_and_project_patch(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, 'executable', lambda name, *a: '/mock/' + name)
    args = providers.command('harness', tmp_path, {'_tools_disabled': True})
    assert args[:4] == ['/mock/rtk', 'proxy', '/mock/harness', 'headless']
    assert args[-2:] == ['--json', '-'] and args.count('--patch') == 2
    assert 'claude' not in ' '.join(args) and 'codex' not in ' '.join(args)
    assert (tmp_path / 'harness-no-web.patch.yml').read_text() == '- id: tool-web\n  disabled: true\n'


def test_harness_final_event_lossless_and_no_thinking_in_logs():
    events = []
    stream = CLIEvents('harness', lambda k, m: events.append((k, m)))
    stream.line('stdout', json.dumps({'type': 'thinking', 'text': 'private reasoning'}))
    stream.line('stdout', json.dumps({'type': 'final', 'text': '{"ok":true}'}))
    assert stream.completed
    assert providers.parse_response('harness', stream.result, structured=True) == {'ok': True}
    assert 'private reasoning' not in str(events)
    with pytest.raises(RuntimeError, match='白名单'):
        stream.line('stdout', json.dumps({'type': 'tool_call', 'tool': 'bash'}))


def test_harness_generate_uses_final_not_intermediate_text(tmp_path, monkeypatch):
    class Process:
        pid = 123
        returncode = 0
        def communicate(self, input=None, timeout=None): pass
    def launch(args, **kw):
        kw['stdout'].write((json.dumps({'type':'text','text':'planning'})+'\n'+
                           json.dumps({'type':'final','text':'{"ok":true}'})+'\n').encode())
        kw['stdout'].flush()
        assert kw['env']['DSH_PERMISSION_MODE'] == 'read-only'
        assert 'DSH_SESSION_ID' not in kw['env']
        return Process()
    monkeypatch.setattr(providers, 'command', lambda *a: ['mock'])
    monkeypatch.setattr(providers.subprocess, 'Popen', launch)
    monkeypatch.setenv('DSH_SESSION_ID', 'do-not-adopt-current-session')
    value = providers.generate('harness', 'test', tmp_path, {}, schema={'type': 'object'})
    assert value == {'ok': True}
