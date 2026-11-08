import time
import pytest

from foot_web.data import public_research
from foot_web.engine import research_stages
from foot_web.engine.providers import ProviderError


def test_collector_reads_only_discovered_public_sources(monkeypatch):
    calls = []
    def call(tool, args, deadline, cancelled):
        calls.append((tool, args))
        return {'text': 'Title: team\nURL: https://example.org/team\nPublished: unknown',
                'sha256': 'fixture', 'tool': tool, 'response': {}}
    monkeypatch.setattr(public_research, '_call', call)
    result = public_research.collect({'home': 'A', 'away': 'B', 'business_date': '2026-11-08'}, time.monotonic()+50)
    assert len(result) == 2
    assert calls[1] == ('exa.web_fetch_exa', {'urls': ['https://example.org/team'], 'maxCharacters': 6000})


def test_no_search_sources_fails_without_ai_or_fetch(monkeypatch):
    monkeypatch.setattr(public_research, '_call', lambda *a: {'text': 'No sources'})
    with pytest.raises(public_research.CollectionError):
        public_research.collect({'home':'A','away':'B','business_date':'2026-11-08'},time.monotonic()+50)


def test_native_research_uses_public_collection_then_same_provider_no_tools(monkeypatch):
    calls, saved, stages = [], [], []
    def generate(provider, prompt, workspace, config, **kwargs):
        calls.append((provider, prompt, config))
        return {'answer': 'actual-return-fixture'}
    monkeypatch.setattr(research_stages, 'native_generate', generate)
    monkeypatch.setattr(research_stages, 'collect', lambda *a, **kw: [
        {'text': 'public content, untrusted', 'tool': 'exa.web_search_exa', 'sha256': 'fixture', 'response': {'raw':'duplicate'}}])
    result = research_stages.run_research_stages('codex', 'request\n=== MATCH INPUT ===\n{}\nextra request', {}, generate,
        time.monotonic()+40, validate=lambda value: value, clean=lambda x:x, cancelled=lambda:False,
        on_event=lambda *a:None, on_response=saved.append, on_invalid=lambda *a:None,on_stage=stages.append)
    assert result == {'answer':'actual-return-fixture'}
    assert calls[0][0] == 'codex' and calls[0][2]['_tools_disabled'] is True
    assert calls[0][2]['_research_effort'] == 'low'
    assert 'duplicate' not in calls[0][1]
    assert 'public content' in calls[0][1]
    assert saved[0]['collector']=='agent-reach/exa'
    assert stages==['public_collection','research']


def test_collection_failure_never_calls_ai(monkeypatch):
    def generate(*a, **kw):
        pytest.fail('AI must not run without source collection')
    def collect(*a, **kw):
        raise public_research.CollectionError('no public data')
    monkeypatch.setattr(research_stages, 'native_generate', generate)
    monkeypatch.setattr(research_stages, 'collect', collect)
    with pytest.raises(ProviderError) as error:
        research_stages.run_research_stages('codex','=== MATCH INPUT ===\n{}',{},generate,
            time.monotonic()+40,validate=lambda x:x,clean=lambda x:x,cancelled=lambda:False,
            on_event=lambda *a:None,on_response=lambda *a:None,on_invalid=lambda *a:None,on_stage=lambda *a:None)
    assert error.value.code=='search_unavailable'


@pytest.mark.parametrize('url', ['http://localhost/admin', 'https://127.0.0.1/admin',
                                'https://host.internal/a', 'https://example.org/a?token=secret'])
def test_collector_does_not_fetch_unsafe_source_links(monkeypatch, url):
    monkeypatch.setattr(public_research, '_call', lambda *a: {'text': 'URL: '+url})
    with pytest.raises(public_research.CollectionError):
        public_research.collect({'home':'A','away':'B','business_date':'2026-11-08'},time.monotonic()+50)
