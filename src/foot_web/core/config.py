"""读取项目根目录 .env（简单 KEY=VALUE 格式），环境变量优先。"""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[3]   # src/foot_web/core/config.py → 项目根
VAR_DIR = PROJECT_DIR / 'var'                        # 运行时数据（git忽略）：app.db、快照、日志
KEYS = ('DINGTALK_CLIENT_ID', 'DINGTALK_CLIENT_SECRET', 'DINGTALK_CORP_ID', 'DINGTALK_REDIRECT_URI',
        'DINGTALK_REDIRECT_URIS', 'DINGTALK_AGENT_ID', 'FOOT_ALLOWED_USER_IDS', 'FOOT_ADMIN_USER_IDS', 'FOOT_NOTIFY_USER_IDS',
        'FOOT_SECRET_KEY', 'FOOT_PORT', 'FOOT_HARNESS_BIN', 'FOOT_CLAUDE_BIN', 'FOOT_CODEX_BIN', 'FOOT_ANALYSIS_TIMEOUT',
        'FOOT_MATCH_TIMEOUT', 'FOOT_ANALYSIS_BUDGET', 'FOOT_RESEARCH_REUSE_MINUTES', 'FOOT_AI_PROVIDER')


def parse_env(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip()
    return values


def load_config(env_path=None):
    values = parse_env(Path(env_path) if env_path else PROJECT_DIR / '.env')
    config = {key: os.environ.get(key, values.get(key, '')) for key in KEYS}
    config['DATA_DIR'] = os.environ.get('FOOT_VAR_DIR', str(VAR_DIR))
    config['PROJECT_DIR'] = str(PROJECT_DIR)
    config['FOOT_AI_PROVIDER'] = config['FOOT_AI_PROVIDER'] or 'codex'
    return config


def runtime_provider(config):
    """Policy owns identity; an optional runtime setting must agree, never drift."""
    from ..services.versions import active_provider
    provider = active_provider(config.get('PROJECT_DIR') or PROJECT_DIR)
    requested = config.get('FOOT_AI_PROVIDER')
    if requested and requested != provider:
        raise ValueError('FOOT_AI_PROVIDER与项目政策runtime_provider不一致，禁止隐式切换')
    return provider


def id_set(value):
    return {item.strip() for item in (value or '').split(',') if item.strip()}
