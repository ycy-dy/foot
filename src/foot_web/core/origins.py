"""One explicit allowlist for OAuth callbacks and notification deep links."""
from urllib.parse import urlsplit

CALLBACK_PATH = '/auth/dingtalk/callback'


def redirect_uris(config):
    values = [config.get('DINGTALK_REDIRECT_URI', ''), *config.get('DINGTALK_REDIRECT_URIS', '').split(',')]
    allowed = set()
    for value in values:
        value = value.strip()
        try:
            parsed = urlsplit(value)
            if (parsed.scheme in ('http', 'https') and parsed.hostname and parsed.port != 0
                    and parsed.path == CALLBACK_PATH and not parsed.username and not parsed.password
                    and not parsed.query and not parsed.fragment):
                allowed.add(value)
        except ValueError:
            continue
    return allowed


def callback_for_origin(config, origin):
    candidate = origin.rstrip('/') + CALLBACK_PATH
    return candidate if candidate in redirect_uris(config) else None
