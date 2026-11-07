"""Required, traceable AI decisions via the isolated DeepSeek Harness boundary."""
import hashlib
import json
import os
from pathlib import Path

from .logs import redact, secret_values
from .providers import ProviderError, generate


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def decide(config, folder, prompt, schema, validate, *, generator=None, on_event=None, cancelled=None):
    """No synthetic success: return only validated DeepSeek Harness output, or raise.

    The directory belongs to a single immutable attempt group. A caller resuming
    must use a fresh group, never overwrite prior AI inputs/outputs.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    # Bound raw input before any processing; never truncate model evidence.
    if len(prompt.encode('utf-8')) > 2_000_000:
        raise ProviderError('invalid_input', 'AI输入超过大小限制，需分批处理；未截断证据')
    secrets = secret_values(config, os.environ)
    safe_prompt = redact(prompt, secrets, limit=None)
    if len(safe_prompt.encode('utf-8')) > 2_000_000:
        raise ProviderError('invalid_input', 'AI输入超过大小限制，需分批处理；未截断证据')
    (folder / 'prompt.txt').write_text(safe_prompt, encoding='utf-8')
    (folder / 'schema.json').write_text(json_text(schema), encoding='utf-8')
    attempts = []

    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return redact(value, secrets, limit=None) if isinstance(value, str) else value

    def emit(provider, kind, message):
        if on_event:
            on_event(provider, kind, redact(message, secrets))

    for provider in ('harness',):
        if cancelled and cancelled():
            raise ProviderError('cancelled', '管理员已取消AI决策')
        emit(provider, 'status', '正在调用DeepSeek Harness推理决策')
        try:
            raw = (generator or generate)(provider, safe_prompt, folder, config, schema=schema,
                                          on_event=lambda kind, text: emit(provider, kind, text),
                                          cancelled=cancelled)
            raw = clean(raw)
            # Preserve the returned content even when semantic validation fails.
            raw_text = json_text(raw)
            (folder / (provider + '.response.json')).write_text(raw_text, encoding='utf-8')
            result = validate(raw)
            if cancelled and cancelled():
                raise ProviderError('cancelled', '管理员已取消AI决策')
        except (ProviderError, ValueError, TypeError, KeyError) as exc:
            code = exc.code if isinstance(exc, ProviderError) else 'invalid_output'
            attempts.append({'provider': provider, 'status': 'failed', 'code': code})
            (folder / 'attempts.json').write_text(json_text(attempts), encoding='utf-8')
            emit(provider, 'error', 'AI决策未完成：' + code)
            if code in ('cancelled', 'cleanup_failed'):
                raise ProviderError(code, 'AI决策已停止：' + code) from None
            continue
        attempts.append({'provider': provider, 'status': 'succeeded', 'code': 'ok'})
        validated_text = json_text(result)
        (folder / 'validated.json').write_text(validated_text, encoding='utf-8')
        (folder / 'attempts.json').write_text(json_text(attempts), encoding='utf-8')
        return {'provider': provider, 'attempts': attempts, 'input_sha256': sha(safe_prompt),
                'response_sha256': sha(raw_text), 'validated_sha256': sha(validated_text),
                'schema_sha256': sha(json_text(schema)), 'model': None,
                'artifact_dir': folder.name, 'result': result}
    raise ProviderError('ai_unavailable', 'DeepSeek Harness未返回有效AI决策，不回退CLI，本次推理未完成')
