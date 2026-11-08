import json
from foot_web.engine.logs import CLIEvents
from foot_web.engine.providers import command


def test_removed_provider_cannot_enter_event_parser():
    import pytest
    from foot_web.engine.logs import CodexToolEventError
    with pytest.raises(CodexToolEventError):
        CLIEvents('claude', lambda *a: None)


def test_no_tools_stage_and_native_search_are_explicit(tmp_path, monkeypatch):
    from foot_web.engine import providers
    monkeypatch.setattr(providers, 'executable', lambda name, *a: '/mock/'+name)
    research = command('harness', tmp_path, {})
    assert 'headless' in research and '--patch' in research
    structure = command('harness', tmp_path, {'_tools_disabled': True})
    patches = [structure[i + 1] for i, value in enumerate(structure[:-1]) if value == '--patch']
    assert len(patches) == 2
    assert (tmp_path / 'harness-no-web.patch.yml').read_text() == '- id: tool-web\n  disabled: true\n'
