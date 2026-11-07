"""Only public CLI events cross the persistent task-log boundary."""
import json
import re

from ..core.privacy import ANSI, ASSIGNMENT, SENSITIVE_KEY, redact, secret_values


class CLIEvents:
    def __init__(self, provider, emit):
        self.provider = provider
        self.emit = emit
        self.pending = {'stdout': '', 'stderr': ''}
        self.result = None
        self.text = ''
        self.partial_text = False
        self.completed = False
        self.tool_ids = set()
        self.public_evidence = []

    def feed(self, channel, text):
        self.pending[channel] += text
        while '\n' in self.pending[channel]:
            line, self.pending[channel] = self.pending[channel].split('\n', 1)
            self.line(channel, line)
        if len(self.pending[channel]) > 2_000_000:
            self.pending[channel] = ''
            self.emit('warning', '一条 CLI 事件超过大小限制，已略过')

    def flush_text(self):
        if self.text.strip():
            self.public_text(self.text)
        self.text = ''

    def finish(self):
        for channel, text in self.pending.items():
            if text.strip():
                self.line(channel, text)
        self.pending = {'stdout': '', 'stderr': ''}
        self.flush_text()

    def line(self, channel, line):
        if channel == 'stderr':
            clean = ANSI.sub('', line).strip()
            # JSON mode sends diagnostics here; never persist arbitrary prompt echoes.
            if re.match(r'^(?:\d{4}-\d\d-\d\d[T ][^\s]+\s+)?'
                        r'(?:WARN(?:ING)?\b|ERROR\b|Error:|error:|Reconnecting\b)', clean):
                self.emit('warning' if re.search(r'\bWARN(?:ING)?\b', clean) else 'error', clean)
            return
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            return
        if not isinstance(event, dict):
            return
        if self.provider == 'claude':
            self.claude(event)
        else:
            self.codex(event)

    def public_text(self, text):
        if not isinstance(text, str) or not text.strip():
            return
        if text.lstrip().startswith('{') and '"report_markdown"' in text:
            self.emit('status', '已收到结构化分析稿，等待校验')
        else:
            self.emit('output', text)

    def claude(self, event):
        kind = event.get('type')
        if kind == 'system' and event.get('subtype') == 'init':
            self.emit('status', 'Claude 会话已初始化 · 模型 ' + str(event.get('model', '待核')))
        elif kind == 'system' and event.get('subtype') == 'api_retry':
            attempt = event.get('attempt', '待核')
            delay = event.get('retry_delay_ms')
            self.emit('warning', f'Claude 上游请求正在重试 · 第 {attempt} 次'
                      + (f' · 等待 {delay / 1000:g} 秒' if isinstance(delay, (int, float)) else ''))
        elif kind == 'stream_event':
            data = event.get('event') or {}
            delta = data.get('delta') or {}
            if data.get('type') == 'content_block_delta' and delta.get('type') == 'text_delta':
                self.partial_text = True
                self.text += delta.get('text', '')
            elif data.get('type') in ('content_block_stop', 'message_stop'):
                self.flush_text()
            elif data.get('type') == 'content_block_start':
                block = data.get('content_block') or {}
                if block.get('type') == 'tool_use' and block.get('name') in ('WebSearch', 'WebFetch'):
                    if block.get('id'):
                        self.tool_ids.add(block['id'])
                    self.emit('tool', str(block['name']) + ' · 开始网页研究')
        elif kind == 'assistant':
            self.flush_text()
            for block in (event.get('message') or {}).get('content', []):
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'text' and not self.partial_text:
                    self.public_text(block.get('text'))
                elif block.get('type') == 'tool_use':
                    tool = block.get('name')
                    data = block.get('input') or {}
                    if tool in ('WebSearch', 'WebFetch'):
                        if block.get('id') not in self.tool_ids:
                            if block.get('id'):
                                self.tool_ids.add(block['id'])
                            self.emit('tool', tool + ' · ' + str(data.get('query') or data.get('url') or '开始网页研究'))
                    elif tool == 'StructuredOutput':
                        self.emit('status', '正在生成结构化分析稿')
            self.partial_text = False
        elif kind == 'user':
            content = (event.get('message') or {}).get('content', [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_result':
                        # Public web results only; never reasoning events or credentials.
                        text = json.dumps(block.get('content', ''), ensure_ascii=False)
                        if sum(map(len, self.public_evidence)) + len(text) <= 500000:
                            self.public_evidence.append(text)
            if isinstance(content, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content):
                self.emit('tool', '网页研究工具已返回结果')
        elif kind == 'result':
            self.flush_text()
            self.result = json.dumps(event, ensure_ascii=False)
            if event.get('is_error') or str(event.get('subtype', '')).startswith('error'):
                self.completed = False
                detail = event.get('result') or '; '.join(str(e) for e in event.get('errors', []))
                self.emit('error', str(detail) or 'Claude 返回执行错误')
            else:
                self.completed = True
                self.emit('status', 'Claude 已返回最终结果')
        elif kind == 'error':
            self.emit('error', str(event.get('message') or 'Claude 返回错误'))

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
                action = item.get('action') or {}
                detail = action.get('query') or action.get('url') or item.get('query') or ''
                state = '完成' if kind == 'item.completed' else '开始'
                self.emit('tool', '网页检索' + state + (' · ' + str(detail) if detail else ''))
            elif item_type == 'error':
                self.emit('error', str(item.get('message') or 'Codex 返回错误'))
            # Reasoning items and arbitrary tool arguments are intentionally omitted.
        elif kind in ('error', 'turn.failed'):
            self.completed = False
            detail = event.get('error') or event.get('message') or 'Codex 返回执行错误'
            if isinstance(detail, dict):
                detail = detail.get('message') or 'Codex 返回执行错误'
            self.emit('error', str(detail))
        elif kind == 'turn.completed':
            self.completed = True
            usage = event.get('usage') or {}
            self.emit('status', '本轮已结束 · 输出 ' + str(usage.get('output_tokens', '待核')) + ' tokens')
