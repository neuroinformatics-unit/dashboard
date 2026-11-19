"""Unit tests for oss_dashboard.fetchers.downloads_pepy."""

from datetime import date

from oss_dashboard.fetchers.downloads_pepy import _current_total, _is_stale


def test_current_total_adds_only_days_after_cached_total():
    entry = {"total": 1000, "through": "2026-11-10"}
    daily = {
        "2026-11-09": 5,
        "2026-11-10": 7,
        "2026-11-11": 3,
        "2026-11-12": 4,
    }
    assert _current_total(entry, daily) == 1007


def test_is_stale():
    today = date(2026, 11, 17)
    assert _is_stale(None, today)
    assert not _is_stale({"fetched_at": "2026-11-01"}, today)
    assert _is_stale({"fetched_at": "2026-10-31"}, today)
    # Same month number in a different year is still stale
    assert _is_stale({"fetched_at": "2025-11-17"}, today)
    # Short month: fetched 1 Feb is stale on 1 Mar despite only 28 days
    assert _is_stale({"fetched_at": "2026-02-01"}, date(2026, 3, 1))
