"""本机只读研究 CLI 边界：Claude 优先策略由 tasks 模块控制。"""
import json
import codecs
import os
import shutil
import signal
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path

from jsonschema import Draft202012Validator
from .logs import CLIEvents, redact, secret_values

SCHEMA = {'type': 'object', 'properties': {'report_markdown': {'type': 'string'}},
          'required': ['report_markdown'], 'additionalProperties': False}
MAX_OUTPUT = 2_000_000


class ProviderError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def executable(name, configured=''):
    candidates = [configured] if configured else [name, str(Path.home() / '.local/bin' / name),
                                                  '/opt/homebrew/bin/' + name, '/usr/local/bin/' + name]
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    raise ProviderError('unavailable', '本机 CLI 未安装或不可执行')


def command(provider, workspace, config):
    binary = executable(provider, config.get('FOOT_' + provider.upper() + '_BIN', ''))
    prefix = [executable('rtk'), 'proxy', binary]
    if provider == 'claude':
        return prefix + ['-p', '--output-format', 'stream-json', '--verbose', '--include-partial-messages',
                         '--json-schema', json.dumps(config.get('_response_schema') or SCHEMA),
                         '--tools', 'WebSearch,WebFetch', '--allowedTools', 'WebSearch,WebFetch',
                         '--permission-mode', 'dontAsk', '--permission-prompts', 'none',
                         '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                         '--setting-sources', 'user', '--settings', '{"disableAllHooks":true}',
                         '--no-chrome', '--no-session-persistence', '--disable-slash-commands']
    if provider != 'codex':
        raise ValueError('无效分析提供方')
    flags = []
    for feature in ('shell_tool', 'unified_exec', 'apps', 'multi_agent', 'computer_use',
                    'browser_use', 'code_mode', 'code_mode_only', 'code_mode_prewarm',
                    'code_mode_host', 'hooks', 'plugins', 'memories'):
        flags.extend(['--disable', feature])
    # Supply a complete disabled transport, not enabled=false alone: native
    # Codex validates transport structure even for disabled desktop MCP entries.
    # Never forward MCP commands, environments or credentials to this child.
    config_path = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'config.toml'
    if config_path.is_file():
        try:
            local_config = tomllib.loads(config_path.read_text(encoding='utf-8'))
            for namespace in ('mcp_servers', 'plugins'):
                entries = local_config.get(namespace, {})
                if entries:
                    disabled = '{enabled=false,command="/usr/bin/false",args=[]}' if namespace == 'mcp_servers' else '{enabled=false}'
                    flags.extend(['-c', namespace + '={' + ','.join(
                        json.dumps(name) + '=' + disabled for name in entries) + '}'])
        except (OSError, ValueError):
            raise ProviderError('configuration', '无法隔离本机MCP配置，未启动研究CLI') from None
    return prefix + ['--search', '--ask-for-approval', 'never', '-c', 'mcp_servers={}', *flags,
                     '-c', 'project_doc_max_bytes=0', 'exec', '--sandbox', 'read-only',
                     '--skip-git-repo-check', '--ephemeral', '--color', 'never', '--json',
                     '--output-schema', str(workspace / 'schema.json'),
                     '--output-last-message', str(workspace / 'response.json'), '-']


def validate_report(report):
    if (not isinstance(report, str) or len(report.encode('utf-8')) > MAX_OUTPUT
            or not report.strip().startswith('# 最终推荐汇总') or '\n' not in report.strip()
            or not report.strip().split('\n', 1)[-1].strip()):
        raise ProviderError('invalid_output', '没有返回有效的完整分析稿')
    return report.strip() + '\n'


def parse_response(provider, text, structured=False):
    try:
        data = json.loads(text)
        if provider == 'claude':
            if isinstance(data, list):
                data = next(item for item in reversed(data) if item.get('type') == 'result')
            if data.get('is_error') or str(data.get('subtype', '')).startswith('error'):
                raise failure(text)
            data = data.get('structured_output') or json.loads(data.get('result', ''))
        if structured:
            if not isinstance(data, dict):
                raise ValueError
            return data
        return validate_report(data['report_markdown'])
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration):
        raise ProviderError('invalid_output', 'CLI 未返回有效的结构化分析稿') from None


def failure(text):
    lowered = text.lower()
    if any(word in lowered for word in ('code-mode host is disabled', 'code mode is unavailable',
                                        'unrecognized feature', 'unknown feature', 'unknown config field')):
        return ProviderError('configuration', 'CLI隔离配置与当前版本不兼容，停止本轮该提供方；请核对Code Mode配置')
    if any(word in lowered for word in ('rate limit', 'rate_limit', '429', 'hit your limit', 'quota',
                                        'usage limit', 'too many requests', 'credit balance', '限额')):
        return ProviderError('rate_limit', '额度不足或触发限流')
    if any(word in lowered for word in ('not logged', 'unauthorized', 'authentication', 'invalid api key', '401', '请先登录')):
        return ProviderError('authentication', '本机 CLI 认证不可用')
    return ProviderError('execution_failed', 'CLI 调用失败')


def _stop_process_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        raise ProviderError('cleanup_failed', '无法清理超时进程，已停止自动回退') from None
    try:
        process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            raise ProviderError('cleanup_failed', '无法清理超时进程，已停止自动回退') from None


def generate(provider, prompt, workspace, config, on_event=None, schema=None, cancelled=None):
    workspace = Path(workspace).resolve() / provider
    workspace.mkdir(mode=0o700)
    if schema:
        config = config | {'_response_schema': schema}
    (workspace / 'schema.json').write_text(json.dumps(schema or SCHEMA))
    args = command(provider, workspace, config)
    env = {key: value for key, value in os.environ.items() if not key.startswith(('DINGTALK_', 'FOOT_'))}
    timeout = max(10, min(3600, int(config.get('FOOT_ANALYSIS_TIMEOUT') or 900)))
    secrets = secret_values(config, os.environ)

    def emit(kind, message):
        if on_event:
            safe = redact(message, secrets)
            if safe:
                on_event(kind, safe)

    stream = CLIEvents(provider, emit)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        offsets = {'stdout': 0, 'stderr': 0}
        decoders = {key: codecs.getincrementaldecoder('utf-8')(errors='replace') for key in offsets}
        started = last_heartbeat = last_output = time.monotonic()

        diagnostic_tail = ''

        def drain():
            nonlocal last_output, diagnostic_tail
            for channel, file in (('stdout', output), ('stderr', errors)):
                while chunk := os.pread(file.fileno(), 65536, offsets[channel]):
                    offsets[channel] += len(chunk)
                    if offsets[channel] > MAX_OUTPUT * 8:
                        raise ProviderError('invalid_output', 'CLI 事件流超过大小限制')
                    decoded = decoders[channel].decode(chunk)
                    stream.feed(channel, decoded)
                    # Deterministic environment incompatibility is not a slow model:
                    # fail and clean up immediately, rather than waiting 180s per match.
                    if channel == 'stderr':
                        diagnostic_tail = (diagnostic_tail + decoded)[-8192:]
                        if failure(diagnostic_tail).code == 'configuration':
                            raise failure(diagnostic_tail)
                    last_output = time.monotonic()

        try:
            project = Path(config['PROJECT_DIR']).resolve() if config.get('PROJECT_DIR') else workspace
            if not project.is_dir():
                raise ProviderError('configuration', '项目运行目录不可用，未启动分析CLI')
            process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=output, stderr=errors,
                                       text=True, encoding='utf-8', errors='replace', env=env,
                                       cwd=project, start_new_session=True)
        except OSError:
            raise ProviderError('unavailable', '本机 CLI 无法启动') from None
        emit('start', f'CLI 进程已启动 · 本次时限 {timeout} 秒')
        try:
            first = True
            while True:
                if cancelled and cancelled():
                    raise ProviderError('cancelled', '管理员已取消分析，CLI已停止')
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(args, timeout)
                try:
                    process.communicate(input=prompt if first else None, timeout=min(.5, remaining))
                    break
                except subprocess.TimeoutExpired:
                    first = False
                    drain()
                    if stream.completed:
                        # A valid terminal result is useful even if a desktop MCP delays CLI shutdown.
                        try:
                            final_text = ((workspace / 'response.json').read_text(encoding='utf-8')
                                          if provider == 'codex' else stream.result)
                            if final_text is None or len(final_text.encode()) > MAX_OUTPUT:
                                raise ValueError
                            final_value = parse_response(provider, final_text, structured=bool(schema))
                            if schema and not Draft202012Validator(schema).is_valid(final_value):
                                raise ValueError
                        except (OSError, ValueError, TypeError, ProviderError):
                            pass
                        else:
                            _stop_process_group(process)
                            drain()
                            stream.finish()
                            emit('status', '完整结果已校验，CLI进程组已回收')
                            return final_value
                    now = time.monotonic()
                    if now - last_heartbeat >= 15:
                        emit('heartbeat', f'CLI 进程仍在运行 · 已用时 {int(now - started)} 秒'
                             f' · 最近 {int(now - last_output)} 秒未收到新事件')
                        last_heartbeat = now
            drain()
            stream.finish()
        except subprocess.TimeoutExpired:
            _stop_process_group(process)
            drain()
            stream.finish()
            emit('error', f'达到 {timeout} 秒时限，已停止 CLI 进程组')
            raise ProviderError('timeout', '本次 CLI 分析超时') from None
        except BaseException:
            _stop_process_group(process)
            raise
        output.seek(0)
        raw = output.read(MAX_OUTPUT + 1)
        errors.seek(0)
        error_text = errors.read(8192).decode('utf-8', errors='replace')
        if process.returncode:
            emit('error', f'CLI 退出码 {process.returncode}')
            raise failure(error_text + raw[:8192].decode('utf-8', errors='replace'))
        if provider == 'codex':
            path = workspace / 'response.json'
            if not path.is_file() or path.stat().st_size > MAX_OUTPUT:
                raise ProviderError('invalid_output', 'Codex 未返回有效分析稿')
            raw = path.read_bytes()
        elif stream.result is not None:
            raw = stream.result.encode('utf-8')
        if len(raw) > MAX_OUTPUT:
            raise ProviderError('invalid_output', 'CLI 返回内容超过大小限制')
        return parse_response(provider, raw.decode('utf-8', errors='replace'), structured=bool(schema))
