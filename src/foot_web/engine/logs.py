"""Only public CLI events cross the persistent task-log boundary."""
import json
import re

from ..core.privacy import ANSI, redact, secret_values


class CodexToolEventError(RuntimeError):
    """An unaccountable or disallowed Codex tool event must stop research."""


class CLIEvents:
    def __init__(self, provider, emit):
        if provider not in {'codex', 'harness'}:
            raise CodexToolEventError('不支持的运行协议，仅接受当前Codex或显式Harness协议')
        self.provider = provider
        self.emit = emit
        self.pending = {'stdout': '', 'stderr': ''}
        self.result = None
        self.completed = False
        self.terminal_error = None
        self.public_evidence = []
        # Codex emits snapshots of the same operation, not new calls. Keep
        # terminal records too, so late/duplicate snapshots cannot spend twice.
        self.codex_tools = {}

    def feed(self, channel, text):
        self.pending[channel] += text
        while '\n' in self.pending[channel]:
            line, self.pending[channel] = self.pending[channel].split('\n', 1)
            self.line(channel, line)
        if len(self.pending[channel]) > 2_000_000:
            raise CodexToolEventError('CLI事件超过大小限制，拒绝截断后继续解析')

    def finish(self):
        for channel, text in self.pending.items():
            if text.strip():
                self.line(channel, text)
        self.pending = {'stdout': '', 'stderr': ''}
        if any(not record['tool'] for record in self.codex_tools.values()):
            raise CodexToolEventError('Codex 网页工具缺少 action 类型，拒绝无法核算的研究')

    def line(self, channel, line):
        if channel == 'stderr':
            clean = ANSI.sub('', line).strip()
            # Diagnostics can contain arbitrary secrets or echoed prompts. Never
            # publish their contents, even when they resemble warning lines.
            if clean and (clean.startswith('Code Mode is unavailable') or
                          re.match(r'^(?:\d{4}-\d\d-\d\d[T ][^\s]+\s+)?'
                                   r'(?:WARN(?:ING)?\b|ERROR\b|Error:|error:|Reconnecting\b)', clean)):
                self.emit('warning', 'CLI 报告诊断信息，已隐藏原始内容')
            return
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            raise CodexToolEventError('CLI stdout不是有效JSONL事件，拒绝旧文本协议') from None
        if not isinstance(event, dict):
            raise CodexToolEventError('CLI事件必须是JSON对象')
        if self.provider == 'harness':
            self.harness(event)
        else:
            self.codex(event)

    def public_text(self, text):
        if not isinstance(text, str) or not text.strip():
            return
        if text.lstrip().startswith('{') and '"report_markdown"' in text:
            self.emit('status', '已收到结构化分析稿，等待校验')
        else:
            self.emit('output', text)

    def harness(self, event):
        kind = event.get('type')
        if kind == 'thinking':
            return  # Never persist private reasoning.
        if kind == 'session':
            self.emit('status', 'DeepSeek Harness 会话已启动')
        elif kind == 'text':
            self.public_text(event.get('text', ''))
        elif kind == 'tool_call':
            tool = event.get('tool', '')
            if tool not in ('web_search', 'web_fetch'):
                raise RuntimeError('Harness暴露了研究白名单以外工具，拒绝继续')
            self.emit('tool', tool + ' · 开始只读网页研究')
        elif kind == 'tool_result':
            if not event.get('truncated'):
                text = str(event.get('result', ''))
                if sum(map(len, self.public_evidence)) + len(text) <= 500000:
                    self.public_evidence.append(text)
            self.emit('tool', 'Harness网页工具已返回结果')
        elif kind == 'final':
            self.result = json.dumps(event, ensure_ascii=False)
            self.completed = True
            self.emit('status', 'DeepSeek Harness 已返回最终结果，等待结构验证')
        elif kind == 'error':
            self.terminal_error = str(event.get('message') or 'Harness执行失败')
            self.emit('error', 'Harness 返回执行错误，已隐藏原始内容')
        else:
            raise CodexToolEventError('未知Harness事件，拒绝旧协议或混合协议')

    def codex_web_tool(self, kind, item):
        """Charge one operation per nonempty id; completion never charges again.

        A start may omit action until a later snapshot. Missing ids, unknown
        actions and contradictory classifications fail closed (no raw payload
        is exposed). A completed-first item is charged before its result event.
        """
        item_id = item.get('id')
        if not isinstance(item_id, str) or not item_id.strip():
            raise CodexToolEventError('Codex 网页工具缺少有效 item.id，拒绝无法核算的研究')
        record = self.codex_tools.setdefault(item_id, {'tool': None, 'done': False})
        action = item.get('action')
        if action is None:
            action = {}
        if not isinstance(action, dict):
            raise CodexToolEventError('Codex 网页工具 action 无效，拒绝继续')
        action_type = action.get('type')
        # Standalone web.run starts before its action is resolved by the CLI.
        # Completion still requires an accountable, concrete web operation.
        if action_type == 'other' and kind != 'item.completed':
            action_type = None
        tools = {'search': 'WebSearch', 'open_page': 'WebFetch', 'find_in_page': 'WebFetch'}
        tool = tools.get(action_type) if isinstance(action_type, str) else None
        if action_type is not None and tool is None:
            raise CodexToolEventError('Codex 网页工具 action 不在只读研究白名单，拒绝继续')
        if tool and record['tool'] and tool != record['tool']:
            raise CodexToolEventError('Codex 同一 item.id 的工具类型冲突，拒绝继续')
        if tool and not record['tool']:
            record['tool'] = tool
            # Do not log arbitrary arguments, result bodies or private reasoning.
            self.emit('tool', tool + ' · 开始只读网页研究')
        if kind == 'item.completed':
            if not record['tool']:
                raise CodexToolEventError('Codex 网页工具完成时仍缺少 action 类型，拒绝无法核算的研究')
            if not record['done']:
                record['done'] = True
                # Deliberately omit canonical names: providers count only calls.
                self.emit('tool', '网页研究工具已返回结果')

    def codex(self, event):
        kind = event.get('type')
        if kind == 'thread.started':
            self.emit('status', 'Codex 会话已连接')
        elif kind == 'turn.started':
            self.emit('status', 'Codex 已开始处理本轮请求')
        elif kind in ('item.started', 'item.updated', 'item.completed'):
            item = event.get('item') or {}
            item_type = item.get('type')
            if item_type == 'agent_message' and kind == 'item.completed':
                self.public_text(item.get('text'))
            elif item_type == 'web_search':
                self.codex_web_tool(kind, item)
            elif item_type in ('command_execution', 'file_change', 'mcp_tool_call',
                               'dynamic_tool_call', 'tool_call'):
                raise CodexToolEventError('Codex 暴露了研究白名单以外工具，拒绝继续')
            elif item_type == 'error':
                self.emit('warning', 'Codex 返回诊断信息，已隐藏原始内容')
            elif item_type not in ('reasoning', 'agent_message', 'todo_list'):
                raise CodexToolEventError('未知Codex item类型，拒绝旧协议或无法核算的工具')
            # Reasoning items and arbitrary tool arguments are intentionally omitted.
        elif kind in ('error', 'turn.failed'):
            detail = event.get('error') or event.get('message') or 'Codex 返回执行错误'
            if isinstance(detail, dict):
                detail = detail.get('message') or 'Codex 返回执行错误'
            self.completed = False
            self.terminal_error = str(detail)
            self.emit('error', 'Codex 返回执行错误，已隐藏原始内容')
        elif kind == 'turn.completed':
            self.completed = self.terminal_error is None
            usage = event.get('usage') or {}
            self.emit('status', '本轮已结束 · 输出 ' + str(usage.get('output_tokens', '待核')) + ' tokens')
        else:
            raise CodexToolEventError('未知Codex事件类型，拒绝旧协议或混合协议')
