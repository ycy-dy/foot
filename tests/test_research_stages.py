"""No real CLI/network calls: bounded evidence collection and safe recovery."""
import json
import os
import time
from pathlib import Path

import pytest

from conftest import FakeFetcher
from test_research_workflow import NOW, payload_for, project
from foot_web.engine.providers import ProviderError
from foot_web.engine.research_stages import run_research_stages
from foot_web.services.research import make_match_prompt, validate_evidence
from foot_web.data.markets import parse_football


def execute(generate, *, validate=lambda result: result, seconds=180):
    responses, failures, stages = [], [], []
    result = run_research_stages(
        'harness', 'original research', {}, generate, time.monotonic() + seconds,
        validate=validate, clean=lambda value: value, cancelled=lambda: False,
        on_event=lambda *args: None, on_response=responses.append,
        on_invalid=lambda exc, code: failures.append(code), on_stage=stages.append)
    return result, responses, failures, stages


def test_valid_evidence_returns_without_a_second_model_call():
    calls = []
    match = parse_football(FakeFetcher().data['football'])[0]
    payload = payload_for(match)

    def generate(provider, prompt, workspace, config, **kwargs):
        calls.append(config)
        return payload

    result, responses, failures, stages = execute(
        generate, validate=lambda value: validate_evidence(value, match, NOW))
    assert result == payload
    assert len(calls) == 1 and not failures
    assert calls[0]['_research_tool_budget'] == {'search': 3, 'fetch': 3}
    assert 130 <= int(calls[0]['FOOT_ANALYSIS_TIMEOUT']) <= 135
    assert stages == ['research'] and responses == [payload]


@pytest.mark.parametrize('code', ['timeout', 'tool_budget'])
def test_public_draft_requires_independent_tool_free_ai_structuring(code):
    calls = []
    match = parse_football(FakeFetcher().data['football'])[0]
    payload = payload_for(match)

    def generate(provider, prompt, workspace, config, **kwargs):
        calls.append((prompt, config))
        if len(calls) == 1:
            exc = ProviderError(code, 'collection stopped')
            exc.public_output = '公开来源 https://example.org/team 未核实首发'
            raise exc
        assert 'https://example.org/team' in prompt
        return payload

    result, responses, failures, stages = execute(
        generate, validate=lambda value: validate_evidence(value, match, NOW))
    assert result == payload and len(calls) == 2
    assert calls[1][1]['_tools_disabled'] is True
    assert calls[1][1]['_research_tool_budget'] == {'search': 0, 'fetch': 0}
    assert failures == [code] and stages == ['research', 'evidence_structure']
    assert responses[0] == {'captured_public_output': '公开来源 https://example.org/team 未核实首发',
                            'stage_status': code}
    assert responses[1] == payload, 'only actual AI structured output can become evidence'


def test_timeout_without_public_output_is_not_fabricated_as_success():
    calls = []

    def generate(*args, **kwargs):
        calls.append(1)
        raise ProviderError('timeout', 'no evidence')

    with pytest.raises(ProviderError, match='no evidence'):
        execute(generate)
    assert len(calls) == 1


def test_invalid_output_only_gets_one_tool_free_repair_and_still_validates():
    calls = []

    def generate(provider, prompt, workspace, config, **kwargs):
        calls.append(config)
        return {'draft': 'not evidence'}

    def reject(value):
        raise ValueError('invalid evidence')

    with pytest.raises(ValueError, match='invalid evidence'):
        execute(generate, validate=reject)
    assert len(calls) == 2 and calls[1]['_tools_disabled'] is True


def test_prompt_explicitly_bounds_collection_and_accepts_unknown():
    match = parse_football(FakeFetcher().data['football'])[0]
    prompt = make_match_prompt(match, 'business policy', NOW)
    assert '最多3次搜索' in prompt and '最多3篇正文' in prompt
    assert '绝不要求23维全部研究' in prompt and 'unknown' in prompt
    assert '收集到可用证据即可交付' in prompt


def test_two_consecutive_timeouts_stop_round_and_preserve_success(project):
    from foot_web.engine.tasks import AnalysisTasks, run_task
    tasks = AnalysisTasks(project, launcher=lambda *args: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')
    calls = []

    def generate(provider, prompt, *args, **kwargs):
        match = json.loads(prompt.split('=== MATCH INPUT ===\n')[1])
        calls.append((provider, match['num']))
        if len(calls) == 1:
            return payload_for(match)
        raise ProviderError('timeout', 'upstream stalled')

    run_task(project, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=NOW)
    result = tasks.get(task['id'])
    assert result['status'] == 'partial'
    assert result['progress']['completed'] == 1
    assert result['progress']['pending'] > 0
    assert len(calls) == 3, 'do not burn all 28 matches after repeated timeouts'


def test_research_rules_exclude_engineering_but_analysis_request_remains_complete(project):
    from foot_web.engine.tasks import AnalysisTasks, run_task
    tasks = AnalysisTasks(project, launcher=lambda *args: os.getpid())
    task, _ = tasks.start('2026-11-04', 'admin1')
    prompts = []

    def generate(provider, prompt, *args, **kwargs):
        prompts.append(prompt)
        raise ProviderError('timeout', 'stop bounded test')

    run_task(project, task['id'], fetcher=FakeFetcher(), generate=generate, as_of=NOW)
    folder = Path(project['PROJECT_DIR']) / 'runs' / '2026-11-04' / task['id']
    source = json.loads((folder / 'input.json').read_text())
    assert 'AGENTS.md' in source['analysis_request']['rules']
    assert all('AGENTS.md' not in prompt for prompt in prompts)
    assert all('GitHub Issue 与跨 Agent' not in prompt for prompt in prompts)
    assert '70' in (folder / 'research-rules.md').read_text()
