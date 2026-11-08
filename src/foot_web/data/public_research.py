"""Bounded public-source collection; no AI decisions or credential management."""
import hashlib
import ipaddress
import json
import os
import shutil
import signal
import subprocess
import time

from urllib.parse import urlsplit


class CollectionError(RuntimeError):
    pass


def _call(tool, arguments, deadline, cancelled):
    binary = shutil.which('mcporter')
    rtk = shutil.which('rtk')
    if not binary or not rtk:
        raise CollectionError('公开资料工具未安装，未开始AI研究')
    args = [rtk, 'proxy', binary, 'call', tool, '--args', json.dumps(arguments, ensure_ascii=False),
            '--output', 'json', '--no-oauth', '--timeout', '20000']
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DINGTALK_', 'FOOT_'))}
    with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          env=env, start_new_session=True) as process:
        try:
            while True:
                if cancelled():
                    raise CollectionError('资料采集已取消')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CollectionError('公开资料采集超时')
                try:
                    output, _ = process.communicate(timeout=min(.5, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode or len(output) > 1_000_000:
                raise CollectionError('公开资料工具失败或返回超过限制')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
    try:
        payload = json.loads(output)
        if payload.get('isError'):
            raise CollectionError('公开资料服务返回错误')
        texts = [row['text'] for row in payload['content'] if row.get('type') == 'text']
        if not texts or not all(isinstance(s, str) for s in texts):
            raise ValueError
        return {'tool': tool, 'arguments': arguments, 'response': payload,
                'sha256': hashlib.sha256(output).hexdigest(), 'text': '\n'.join(texts)}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise CollectionError('公开资料工具返回不符合当前JSON契约') from None


def collect(match, deadline, *, cancelled=lambda: False, on_event=lambda *a: None):
    """One search and at most two public-page reads within the original deadline."""
    query = f"{match['home']} {match['away']} {match['business_date']} official team news lineup injuries preview"
    on_event('status', '公开资料采集：agent-reach / Exa，研究判断仍由Codex完成')
    search = _call('exa.web_search_exa', {
        'query': query, 'numResults': 3,
        'objective': '优先俱乐部/联赛官方本场赛前名单伤停与战术资料，排除投注预测；列真实来源和时点，不能补造。',
    }, min(deadline, time.monotonic() + 22), cancelled)
    # Exa's current MCP contract wraps its public result list in text blocks.
    urls = []
    for line in search['text'].splitlines():
        if line.startswith('URL: '):
            url = line[5:].strip()
            parsed = urlsplit(url)
            host = parsed.hostname or ''
            try:
                public = ipaddress.ip_address(host).is_global
            except ValueError:
                public = bool('.' in host and not host.endswith(('.local', '.localhost', '.internal')))
            if (parsed.scheme == 'https' and public and not parsed.username
                    and not parsed.password and not parsed.query and url not in urls):
                urls.append(url)
    if not urls:
        raise CollectionError('公开搜索未返回可定位来源，不生成空证据报告')
    receipts = [search]
    on_event('status', '公开搜索已返回；读取至多两篇来源正文，未验证事实或提高评分')
    try:
        receipts.append(_call('exa.web_fetch_exa', {'urls': urls[:2], 'maxCharacters': 6000},
                              min(deadline, time.monotonic() + 22), cancelled))
    except CollectionError:
        if cancelled():
            raise
        # Search excerpts remain explicitly excerpts, never confirmed full text.
        on_event('warning', '来源正文未完整取得，仅保留搜索摘要并标注缺口')
    return receipts
