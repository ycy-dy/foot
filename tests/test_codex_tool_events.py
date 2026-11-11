"""Synthetic public Codex events only: never launch a CLI or read runtime data."""
import json
import pytest

from foot_web.engine import providers
from foot_web.engine.logs import CLIEvents, CodexToolEventError


def item(kind='started', item_id='web-1', action='search', **extra):
    payload = {'type': 'web_search', 'id': item_id, **extra}
    if action is not None:
        payload['action'] = {'type': action}
    return {'type': 'item.' + kind, 'item': payload}


def capture():
    events = []
    return CLIEvents('codex', lambda kind, text: events.append((kind, text))), events


def calls(events, tool):
    return sum(kind == 'tool' and text.startswith(tool + ' · ') for kind, text in events)


@pytest.mark.parametrize('action,tool', [
    ('search', 'WebSearch'), ('open_page', 'WebFetch'), ('find_in_page', 'WebFetch'),
])
@pytest.mark.parametrize('order', [
    ['started', 'started', 'updated', 'updated', 'completed', 'completed'],
    ['completed', 'updated', 'started', 'completed'],
    ['updated', 'completed', 'started'],
])
def test_each_id_charges_exactly_once_for_every_public_action(action, tool, order):
    stream, events = capture()
    for phase in order:
        stream.codex(item(phase, action=action))
    stream.finish()
    assert calls(events, tool) == 1
    assert calls(events, 'WebSearch' if tool == 'WebFetch' else 'WebFetch') == 0
    assert events.count(('tool', '网页研究工具已返回结果')) == 1


def test_interleaved_ids_and_delayed_action_and_missing_completion_action():
    stream, events = capture()
    stream.codex(item(action=None))
    stream.codex(item(item_id='web-2', action='open_page'))
    stream.codex(item('updated', action='search'))
    stream.codex(item('completed', action=None))
    stream.codex(item('completed', item_id='web-2', action=None))
    stream.finish()
    assert calls(events, 'WebSearch') == calls(events, 'WebFetch') == 1


def test_standalone_pending_other_requires_concrete_completion():
    stream, events = capture()
    stream.codex(item(action='other'))
    assert not events
    stream.codex(item('updated', action='search'))
    stream.codex(item('completed', action='search'))
    stream.finish()
    assert calls(events, 'WebSearch') == 1
    stream, _ = capture()
    stream.codex(item(action='other'))
    with pytest.raises(CodexToolEventError):
        stream.codex(item('completed', action='other'))


@pytest.mark.parametrize('item_id', [None, '', ' ', 12, [], {}])
def test_missing_or_unusable_ids_fail_closed(item_id):
    stream, events = capture()
    with pytest.raises(CodexToolEventError, match='item.id'):
        stream.codex(item(item_id=item_id))
    assert not events


@pytest.mark.parametrize('action', ['shell', '', 3, {}, []])
def test_unknown_action_fails_closed_without_logging_payload(action):
    stream, events = capture()
    with pytest.raises(CodexToolEventError):
        stream.codex(item(action=action, text='private reasoning', query='secret query'))
    assert not events


def test_unclassified_completed_or_finished_stream_fails_closed():
    stream, _ = capture()
    with pytest.raises(CodexToolEventError):
        stream.codex(item('completed', action=None))
    stream, _ = capture()
    stream.codex(item(action=None))
    with pytest.raises(CodexToolEventError):
        stream.finish()


def test_same_id_cannot_change_budget_category():
    stream, events = capture()
    stream.codex(item())
    with pytest.raises(CodexToolEventError, match='冲突'):
        stream.codex(item('updated', action='open_page'))
    assert calls(events, 'WebSearch') == 1
    assert calls(events, 'WebFetch') == 0


@pytest.mark.parametrize('tool', ['command_execution', 'file_change', 'mcp_tool_call',
                                  'dynamic_tool_call', 'tool_call'])
def test_non_web_tools_fail_closed(tool):
    stream, events = capture()
    with pytest.raises(CodexToolEventError, match='白名单'):
        stream.codex({'type': 'item.started', 'item': {'type': tool, 'arguments': 'private'}})
    assert not events


def test_only_public_messages_and_errors_cross_log_boundary():
    stream, events = capture()
    stream.codex({'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'PRIVATE'}})
    stream.codex(item('completed', text='PRIVATE', result='PRIVATE'))
    stream.codex({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'public'}})
    stream.codex({'type': 'item.completed', 'item': {'type': 'error', 'message': 'SECRET_ITEM'}})
    stream.codex({'type': 'turn.failed', 'error': {'message': 'SECRET_FAILURE'}})
    assert ('output', 'public') in events
    assert ('warning', 'Codex 返回诊断信息，已隐藏原始内容') in events
    assert ('error', 'Codex 返回执行错误，已隐藏原始内容') in events
    assert not stream.completed
    assert all(secret not in str(events) for secret in ('PRIVATE', 'SECRET_ITEM', 'SECRET_FAILURE'))


def run_fake(tmp_path, monkeypatch, payloads, budget, *, cancelled=None, disabled=False):
    """Exercise real budget/cleanup code with entirely in-memory fake process."""
    killed = []
    events = []

    class Process:
        pid = 12345
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return None

    def launch(args, **kwargs):
        terminal = {'type': 'turn.completed', 'usage': {'output_tokens': 1}}
        kwargs['stdout'].write(('\n'.join(json.dumps(p) for p in [*payloads, terminal]) + '\n').encode())
        kwargs['stdout'].flush()
        (tmp_path / 'codex' / 'response.json').write_text(json.dumps({'ok': True}))
        return Process()

    monkeypatch.setattr(providers, 'command', lambda *a: ['fake-codex'])
    monkeypatch.setattr(providers.os, 'environ', {})
    monkeypatch.setattr(providers.subprocess, 'Popen', launch)
    monkeypatch.setattr(providers.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    config = {'_research_tool_budget': budget, '_tools_disabled': disabled}
    result = providers.generate('codex', 'synthetic', tmp_path, config,
                                schema={'type': 'object'}, cancelled=cancelled,
                                on_event=lambda kind, text: events.append((kind, text)))
    return result, events, killed


def test_real_provider_budget_accepts_duplicate_updates_and_fetch(tmp_path, monkeypatch):
    payloads = [item(phase) for phase in ('started', 'updated', 'updated', 'completed')]
    payloads += [item('completed', item_id='web-2', action='open_page')]
    result, events, killed = run_fake(tmp_path, monkeypatch, payloads, {'search': 1, 'fetch': 1})
    assert result == {'ok': True}
    assert calls(events, 'WebSearch') == calls(events, 'WebFetch') == 1
    assert not killed


@pytest.mark.parametrize('action,budget', [('search', {'search': 0}), ('open_page', {'fetch': 0}),
                                          ('find_in_page', {'search': 100, 'fetch': 0})])
def test_completed_first_enforces_correct_provider_budget(tmp_path, monkeypatch, action, budget):
    with pytest.raises(providers.ProviderError) as error:
        run_fake(tmp_path, monkeypatch, [item('completed', action=action)], budget)
    assert error.value.code == 'tool_budget'


def test_protocol_error_stops_process_group(tmp_path, monkeypatch):
    killed = []
    original = providers._stop_process_group
    monkeypatch.setattr(providers, '_stop_process_group', lambda process: (killed.append(process.pid), original(process)))
    with pytest.raises(providers.ProviderError) as error:
        run_fake(tmp_path, monkeypatch, [item(item_id=None)], {'search': 10})
    assert error.value.code == 'tool_protocol'
    assert killed == [12345]


def test_cancel_stops_without_counting_buffered_events(tmp_path, monkeypatch):
    killed = []
    monkeypatch.setattr(providers, '_stop_process_group', lambda process: killed.append(process.pid))
    with pytest.raises(providers.ProviderError) as error:
        run_fake(tmp_path, monkeypatch, [item()], {'search': 0}, cancelled=lambda: True)
    assert error.value.code == 'cancelled'
    assert killed == [12345]


@pytest.mark.parametrize('status', ['failed', 'cancelled'])
def test_failed_or_cancelled_item_still_accounts_attempt_only_once(status):
    stream, events = capture()
    stream.codex(item(status=status))
    stream.codex(item('completed', status=status))
    stream.codex(item('completed', status=status))
    stream.codex({'type': 'turn.failed', 'error': {'message': status}})
    assert calls(events, 'WebSearch') == 1
    assert not stream.completed


def test_no_tools_stage_rejects_unexpected_web_operation(tmp_path, monkeypatch):
    with pytest.raises(providers.ProviderError) as error:
        run_fake(tmp_path, monkeypatch, [item()], {}, disabled=True)
    assert error.value.code == 'tool_protocol'


@pytest.mark.parametrize('action', ['query', 'open', 'find'])
def test_legacy_action_aliases_are_rejected(action):
    stream, _ = capture()
    with pytest.raises(CodexToolEventError):
        stream.codex(item('completed', action=action))


@pytest.mark.parametrize('event', [
    {'type': 'session'}, {'type': 'assistant'}, {'type': 'result'},
    {'type': 'item.completed', 'item': {'type': 'new_unknown_tool'}},
])
def test_old_or_unknown_protocol_never_silently_succeeds(event):
    stream, _ = capture()
    with pytest.raises(CodexToolEventError):
        stream.codex(event)
