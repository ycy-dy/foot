import json
from foot_web.engine.logs import CLIEvents
from foot_web.engine.providers import command


def test_streaming_and_complete_tool_events_count_once():
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
    monkeypatch.setenv('CODEX_HOME', str(tmp_path))
    research = command('codex', tmp_path, {})
    assert 'standalone_web_search' in research
    collect = command('claude', tmp_path, {'_tools_disabled': True})
    assert collect[collect.index('--tools')+1] == ''
    assert '--system-prompt' in collect
    structure = command('codex', tmp_path, {'_tools_disabled': True})
    assert '--search' not in structure and 'web_search="disabled"' in structure
