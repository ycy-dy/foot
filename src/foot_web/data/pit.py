"""赛前多时点快照契约（规格038）。

只读、纯函数：给定比赛开球时间与一批快照捕获时间，回答"某个时点能不能用某份
快照"。核心规则是 as-of 语义——**只能取该时点及之前的数据**，晚于边界的快照
不得回填为更早时点的基线，从结构上禁止收盘赔率冒充 T-24h 基线。

本模块不写文件、不联网，也未接入推荐/发布链路。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')

ASPECTS: tuple[tuple[str, timedelta], ...] = (
    ('T-24h', timedelta(hours=24)),
    ('T-6h', timedelta(hours=6)),
    ('T-90m', timedelta(minutes=90)),
)


def as_datetime(value) -> datetime:
    """统一成无时区的北京时间，避免 naive/aware 混比。"""
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace('/', '-'))
    if moment.tzinfo is not None:
        moment = moment.astimezone(TZ).replace(tzinfo=None)
    return moment


def aspect_boundaries(kickoff) -> dict[str, datetime]:
    """返回各赛前时点的具体边界时间。"""
    kick = as_datetime(kickoff)
    return {name: kick - delta for name, delta in ASPECTS}


def classify(captured_at, kickoff) -> str:
    """判断快照落在哪个时间窗，用于标注数据新鲜度，不用于替代选择。"""
    captured = as_datetime(captured_at)
    kick = as_datetime(kickoff)
    if captured >= kick:
        return 'post-kickoff'
    if captured <= kick - ASPECTS[0][1]:
        return 'pre-T-24h'
    if captured <= kick - ASPECTS[1][1]:
        return 'T-24h'
    if captured <= kick - ASPECTS[2][1]:
        return 'T-6h'
    return 'T-90m'


def select_as_of(entries, as_of, *, time_key: str = 'captured_at'):
    """取不晚于 as_of 的最近一条记录；没有则返回 None。

    任何晚于 as_of 的记录都不会被选中，这是防止领先偏差的唯一入口。
    """
    limit = as_datetime(as_of)
    eligible = [entry for entry in entries if as_datetime(entry[time_key]) <= limit]
    if not eligible:
        return None
    return max(eligible, key=lambda entry: (as_datetime(entry[time_key]), str(entry.get('file', ''))))


def validate_no_lookahead(entry, as_of, *, time_key: str = 'captured_at') -> None:
    """显式校验：该记录晚于时点即拒绝使用。"""
    if as_datetime(entry[time_key]) > as_datetime(as_of):
        raise ValueError(f'快照 {entry.get(time_key)} 晚于时点 {as_of}，禁止作为该时点基线')


def coverage(entries, kickoff, *, time_key: str = 'captured_at') -> dict:
    """逐时点覆盖报告：可用性、实际捕获时间、陈旧分钟数与缺口。"""
    kick = as_datetime(kickoff)
    captured = sorted((as_datetime(entry[time_key]) for entry in entries if entry.get(time_key)))
    rejected = sum(1 for moment in captured if moment >= kick)
    pre_match = [moment for moment in captured if moment < kick]

    report = {
        'kickoff': kick.isoformat(sep=' ', timespec='minutes'),
        'captures': len(captured),
        'lookahead_rejected': rejected,
        'aspects': {},
        'closing': None,
        'missing': [],
    }
    for name, delta in ASPECTS:
        boundary = kick - delta
        chosen = select_as_of(entries, boundary, time_key=time_key)
        stale = None
        when = None
        if chosen is not None:
            when = as_datetime(chosen[time_key])
            stale = int((boundary - when).total_seconds() // 60)
        report['aspects'][name] = {
            'available': chosen is not None,
            'captured_at': when.isoformat(sep=' ', timespec='minutes') if when else None,
            'stale_minutes': stale,
        }
        if chosen is None:
            report['missing'].append(name)

    if pre_match:
        closing = pre_match[-1]
        report['closing'] = {
            'captured_at': closing.isoformat(sep=' ', timespec='minutes'),
            'lead_minutes': int((kick - closing).total_seconds() // 60),
        }
    return report
