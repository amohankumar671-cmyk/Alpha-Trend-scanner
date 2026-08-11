"""Tests for closed-bar history handling (no network)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from datafeed import (
    bar_is_closed,
    drop_incomplete_bar,
    ensure_datetime_index,
    history_status,
    normalize_symbol,
)


def _frame(last_start: datetime, n: int = 5, freq_minutes: int = 15) -> pd.DataFrame:
    idx = pd.date_range(end=last_start, periods=n, freq=f"{freq_minutes}min", tz=ZoneInfo("Asia/Kolkata"))
    return pd.DataFrame(
        {
            "Open": range(n),
            "High": range(n),
            "Low": range(n),
            "Close": range(n),
            "Volume": [1000] * n,
        },
        index=idx,
    )


def test_normalize_symbol_nse():
    assert normalize_symbol("reliance") == "RELIANCE.NS"
    assert normalize_symbol("RELIANCE.NS") == "RELIANCE.NS"
    assert normalize_symbol("^NSEI") == "^NSEI"


def test_drop_incomplete_15m_bar():
    # Bar started 15:00 IST; at 15:10 it is still forming → drop
    last = datetime(2026, 8, 11, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    now = datetime(2026, 8, 11, 15, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
    df = _frame(last, n=10, freq_minutes=15)
    out, dropped = drop_incomplete_bar(df, "15m", now=now)
    assert dropped is True
    assert len(out) == len(df) - 1


def test_keep_closed_15m_bar():
    last = datetime(2026, 8, 11, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    now = datetime(2026, 8, 11, 15, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
    df = _frame(last, n=10, freq_minutes=15)
    out, dropped = drop_incomplete_bar(df, "15m", now=now)
    assert dropped is False
    assert len(out) == len(df)


def test_bar_is_closed_1h():
    start = pd.Timestamp("2026-08-11 10:15:00", tz="Asia/Kolkata")
    assert bar_is_closed(start, "1h", now=datetime(2026, 8, 11, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata"))) is False
    assert bar_is_closed(start, "1h", now=datetime(2026, 8, 11, 11, 15, tzinfo=ZoneInfo("Asia/Kolkata"))) is True


def test_history_status_building_message():
    status = history_status(10, ap=14, dropped_forming=True)
    assert status["ready"] is False
    assert "Building history" in status["message"]
    assert "in-progress bar excluded" in status["message"]
    ready = history_status(30, ap=14, dropped_forming=True)
    assert ready["ready"] is True


def test_ensure_datetime_index_fixes_plain_index():
    """Regression: string Index used to crash resample with the banner error."""
    last = datetime(2026, 8, 11, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    df = _frame(last, n=12, freq_minutes=15)
    broken = df.copy()
    broken.index = pd.Index([str(x) for x in broken.index])
    assert not isinstance(broken.index, pd.DatetimeIndex)

    fixed = ensure_datetime_index(broken)
    assert isinstance(fixed.index, pd.DatetimeIndex)
    # Must be resample-safe after fix
    resampled = fixed.resample("1h").agg({"Close": "last"}).dropna()
    assert len(resampled) > 0


def test_drop_incomplete_works_after_string_index():
    last = datetime(2026, 8, 11, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    now = datetime(2026, 8, 11, 15, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
    df = _frame(last, n=10, freq_minutes=15)
    df.index = pd.Index([str(x) for x in df.index])
    out, dropped = drop_incomplete_bar(df, "15m", now=now)
    assert dropped is True
    assert isinstance(out.index, pd.DatetimeIndex)


def test_daily_not_dropped_by_closed_helper():
    last = datetime(2026, 8, 11, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    df = _frame(last, n=5, freq_minutes=24 * 60)
    # force daily index
    df.index = pd.date_range("2026-08-01", periods=5, freq="D", tz=ZoneInfo("Asia/Kolkata"))
    out, dropped = drop_incomplete_bar(df, "1d")
    assert dropped is False
    assert len(out) == 5


if __name__ == "__main__":
    test_normalize_symbol_nse()
    test_drop_incomplete_15m_bar()
    test_keep_closed_15m_bar()
    test_bar_is_closed_1h()
    test_history_status_building_message()
    test_ensure_datetime_index_fixes_plain_index()
    test_drop_incomplete_works_after_string_index()
    test_daily_not_dropped_by_closed_helper()
    print("Closed-bar tests passed.")
