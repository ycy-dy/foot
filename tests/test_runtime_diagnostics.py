from foot_web.services.runtime_diagnostics import attempt_diagnostics


def test_error_counts_do_not_expose_raw_prompts_or_messages():
    attempts = [{'provider': 'codex', 'status': 'failed', 'code': 'configuration', 'message': 'private raw'},
                {'provider': 'codex', 'status': 'failed', 'code': 'configuration'},
                {'provider': 'claude', 'status': 'succeeded', 'code': 'ok'}]
    result = attempt_diagnostics(attempts)
    assert len(result) == 1 and result[0]['count'] == 2
    assert result[0]['code'] == 'configuration'
    assert 'private raw' not in str(result)
    assert attempt_diagnostics([]) == []
