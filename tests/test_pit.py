"""038 赛前多时点快照契约测试（纯函数）。"""

from datetime import datetime, timedelta

import pytest

from foot_web.data import pit

KICKOFF = datetime(2026, 11, 8, 20, 0)


def test_boundaries_are_kickoff_minus_offsets():
    bounds = pit.aspect_boundaries(KICKOFF)
    assert bounds['T-24h'] == datetime(2026, 11, 7, 20, 0)
    assert bounds['T-6h'] == datetime(2026, 11, 8, 14, 0)
    assert bounds['T-90m'] == datetime(2026, 11, 8, 18, 30)


def test_classify_windows():
    assert pit.classify(datetime(2026, 11, 7, 18, 0), KICKOFF) == 'pre-T-24h'
    assert pit.classify(datetime(2026, 11, 7, 21, 0), KICKOFF) == 'T-24h'
    assert pit.classify(datetime(2026, 11, 8, 15, 0), KICKOFF) == 'T-6h'
    assert pit.classify(datetime(2026, 11, 8, 19, 0), KICKOFF) == 'T-90m'
    assert pit.classify(datetime(2026, 11, 8, 20, 0), KICKOFF) == 'post-kickoff'


def test_as_of_never_returns_future_snapshot():
    entries = [{'captured_at': datetime(2026, 11, 7, 22, 0), 'file': 'closing'}]  # 距开球 22 小时
    assert pit.select_as_of(entries, datetime(2026, 11, 7, 20, 0)) is None
    entries.append({'captured_at': datetime(2026, 11, 7, 19, 0), 'file': 'early'})
    chosen = pit.select_as_of(entries, datetime(2026, 11, 7, 20, 0))
    assert chosen['file'] == 'early'


def test_closing_only_snapshot_cannot_fill_earlier_aspects():
    entries = [{'captured_at': datetime(2026, 11, 8, 19, 55)}]
    report = pit.coverage(entries, KICKOFF)
    assert report['missing'] == ['T-24h', 'T-6h', 'T-90m']
    assert report['aspects']['T-24h']['available'] is False
    assert report['closing']['lead_minutes'] == 5


def test_coverage_uses_as_of_vintages_and_reports_staleness():
    entries = [
        {'captured_at': datetime(2026, 11, 7, 18, 0)},
        {'captured_at': datetime(2026, 11, 8, 12, 0)},
        {'captured_at': datetime(2026, 11, 8, 18, 0)},
    ]
    report = pit.coverage(entries, KICKOFF)
    assert report['aspects']['T-24h']['captured_at'] == '2026-11-07 18:00'
    assert report['aspects']['T-24h']['stale_minutes'] == 120
    assert report['aspects']['T-6h']['stale_minutes'] == 120
    assert report['aspects']['T-90m']['stale_minutes'] == 30
    assert report['missing'] == []
    assert report['closing']['lead_minutes'] == 120


def test_boundary_equality_is_allowed_but_one_minute_later_is_not():
    on_time = {'captured_at': datetime(2026, 11, 7, 20, 0)}
    late = {'captured_at': datetime(2026, 11, 7, 20, 1)}
    assert pit.select_as_of([on_time], datetime(2026, 11, 7, 20, 0)) is not None
    assert pit.select_as_of([late], datetime(2026, 11, 7, 20, 0)) is None
    with pytest.raises(ValueError):
        pit.validate_no_lookahead(late, datetime(2026, 11, 7, 20, 0))


def test_post_kickoff_snapshots_are_rejected():
    entries = [
        {'captured_at': datetime(2026, 11, 8, 19, 0)},
        {'captured_at': datetime(2026, 11, 8, 21, 0)},
    ]
    report = pit.coverage(entries, KICKOFF)
    assert report['lookahead_rejected'] == 1
    assert report['closing']['captured_at'] == '2026-11-08 19:00'


def test_timezone_aware_values_are_normalised():
    aware = datetime(2026, 11, 7, 21, 0, tzinfo=pit.TZ)
    assert pit.classify(aware, KICKOFF) == 'T-24h'
    report = pit.coverage([{'captured_at': aware}], KICKOFF)
    assert report['closing']['captured_at'] == '2026-11-07 21:00'
