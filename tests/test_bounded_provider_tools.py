import json
from foot_web.engine.logs import CLIEvents
from foot_web.engine.providers import command


def test_historical_claude_parser_streaming_and_complete_tool_events_count_once():
    # Read-only historical event parsing; never execute a legacy provider.
    events = []
    stream = CLIEvents('claude', lambda kind, text: events.append((kind, text)))
    block = {'type': 'tool_use', 'id': 'call-1', 'name': 'WebSearch', 'input': {'query': 'public query'}}
    stream.claude({'type': 'stream_event', 'event': {'type': 'content_block_start', 'content_block': block}})
    stream.claude({'type': 'assistant', 'message': {'content': [block]}})
    assert sum(kind == 'tool' for kind, _ in events) == 1
    stream.claude({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'public result URL'}]}})
    assert stream.public_evidence == [json.dumps('public result URL')]


def test_no_tools_stage_and_native_search_are_explicit(tmp_path, monkeypatch):
    from foot_web.engine import providers
    monkeypatch.setattr(providers, 'executable', lambda name, *a: '/mock/'+name)
    research = command('harness', tmp_path, {})
    assert 'headless' in research and '--patch' in research
    structure = command('harness', tmp_path, {'_tools_disabled': True})
    patches = [structure[i + 1] for i, value in enumerate(structure[:-1]) if value == '--patch']
    assert len(patches) == 2
    assert (tmp_path / 'harness-no-web.patch.yml').read_text() == '- id: tool-web\n  disabled: true\n'
