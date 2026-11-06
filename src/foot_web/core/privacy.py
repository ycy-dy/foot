"""Shared redaction for public logs, persisted AI artifacts and notification summaries."""
import re

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
SENSITIVE_KEY = re.compile(r'token|secret|password|credential|api.?key|authorization', re.I)
# Anchor each key once; avoid quadratic matching on complete AI prompts.
ASSIGNMENT = re.compile(
    r'''(?<![\w.-])(["']?(?=[\w.-]*(?:api[_-]?key|token|secret|password|credential|authorization))
    [\w.-]+["']?\s*[:=]\s*)("[^"]*"|'[^']*'|[^\s,;&"'\\]+)''', re.I | re.X)


def redact(text, secrets=(), limit=4000):
    text = ANSI.sub('', str(text))
    for secret in sorted(set(secrets), key=len, reverse=True):
        if len(secret) >= 4:
            text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'(?i)\bBearer\s+[^\s"\'<>;,]+', 'Bearer [REDACTED]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED]', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', '[REDACTED]', text)
    text = re.sub(r'(https?://)[^/\s@]+:[^/\s@]+@', r'\1[REDACTED]@', text)
    def hide_assignment(match):
        value = match[2]
        if value in ('null', 'true', 'false'):
            return match[0]
        quote = value[0] if value[0] in ('"', "'") else ''
        return match[1] + quote + '[REDACTED]' + quote
    text = ASSIGNMENT.sub(hide_assignment, text)
    text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', text)
    return (text if limit is None else text[:limit]).strip()


def secret_values(config, env):
    return [str(value) for source in (config, env) for key, value in source.items()
            if value and SENSITIVE_KEY.search(key)]
