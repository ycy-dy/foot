"""Public attempt counters only; no raw prompt, response or credential exposure."""
from collections import Counter

HINTS = {
    'configuration': '提供方隔离配置不兼容，本轮跳过；核对Harness profile/工具授权，不自动扩权或回退旧CLI。',
    'invalid_output': 'AI返回未满足证据契约；仅允许一次预算内结构修复，不降低来源门槛。',
    'timeout': '单次预算超时，已清理进程；可保留检查点，不能把存活当研究成功。',
    'authentication': 'CLI认证不可用，请本人检查授权；不索取Token。',
    'rate_limit': '额度或限流，本轮跳过不可用提供方，不自动付费或无限重试。',
}


def attempt_diagnostics(attempts):
    counts = Counter((a.get('provider', 'unknown'), a.get('code', 'unknown'))
                     for a in attempts if a.get('status') == 'failed')
    return [{'provider': provider, 'code': code, 'count': count,
             'hint': HINTS.get(code, '查看已脱敏日志与保留的失败工件；不要盲目重复提交。')}
            for (provider, code), count in sorted(counts.items())]
