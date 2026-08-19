"""Offline tests for auto-scan scheduling helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from autoscan import (
    IST,
    format_duration,
    is_nse_session,
    resolve_interval_minutes,
    seconds_until_due,
    should_run_now,
    shortest_interval_minutes,
)


def test_shortest_interval():
    assert shortest_interval_minutes(["5m", "15m", "1h"]) == 5
    assert shortest_interval_minutes(["15m", "1d"]) == 15
    assert shortest_interval_minutes(["1d", "1wk"]) == 1440


def test_resolve_modes():
    assert resolve_interval_minutes(["5m", "1h"], mode="match_tf") == 5
    assert resolve_interval_minutes(["5m", "1h"], mode="custom", custom_minutes=20) == 20


def test_seconds_until_due():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    last = now - timedelta(minutes=3)
    assert seconds_until_due(last, 5, now=now) == 120
    assert seconds_until_due(None, 5, now=now) == 0
    assert seconds_until_due(now - timedelta(minutes=10), 5, now=now) == 0


def test_should_run_requires_manual_arm():
    now = datetime(2026, 8, 12, 10, 30, tzinfo=IST)  # Wed in session
    due, reason = should_run_now(
        auto_enabled=True,
        last_finished_at=None,
        interval_minutes=5,
        market_hours_only=True,
        scan_running=False,
        now=now,
    )
    assert due is False
    assert "manual" in reason.lower() or "arm" in reason.lower()


def test_should_run_when_due():
    now = datetime(2026, 8, 12, 10, 30, tzinfo=IST)
    last = now - timedelta(minutes=6)
    due, reason = should_run_now(
        auto_enabled=True,
        last_finished_at=last,
        interval_minutes=5,
        market_hours_only=True,
        scan_running=False,
        now=now,
    )
    assert due is True
    assert reason == "Due"


def test_market_hours_gate():
    sunday = datetime(2026, 8, 16, 11, 0, tzinfo=IST)
    assert is_nse_session(sunday) is False
    weekday_open = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    assert is_nse_session(weekday_open) is True
    after_close = datetime(2026, 8, 12, 16, 0, tzinfo=IST)
    assert is_nse_session(after_close) is False

    due, reason = should_run_now(
        auto_enabled=True,
        last_finished_at=after_close - timedelta(minutes=30),
        interval_minutes=5,
        market_hours_only=True,
        scan_running=False,
        now=after_close,
    )
    assert due is False
    assert "market" in reason.lower()


def test_format_duration():
    assert format_duration(65) == "1m 05s"
    assert format_duration(5) == "5s"


if __name__ == "__main__":
    test_shortest_interval()
    test_resolve_modes()
    test_seconds_until_due()
    test_should_run_requires_manual_arm()
    test_should_run_when_due()
    test_market_hours_gate()
    test_format_duration()
    print("Auto-scan tests passed.")
