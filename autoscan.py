"""
Auto-scan scheduling helpers for the dashboard and CLI loop.

Workable approach:
  - Pick an interval from the shortest selected timeframe (e.g. 5m → 5 minutes)
    or a custom N minutes.
  - Start the next scan only AFTER the previous one finishes (no overlap).
  - Optionally skip when NSE cash session is closed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Minutes between closed-bar refreshes (intraday frames matter most).
TF_MINUTES: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "60m": 60,
    "4h": 240,
    "1d": 1440,
    "1wk": 10080,
}

# NSE equity cash session (IST). Slightly past 15:30 so the last bar can settle.
NSE_OPEN = time(9, 15)
NSE_CLOSE = time(15, 35)


def shortest_interval_minutes(timeframes: list[str] | tuple[str, ...]) -> int:
    """Smallest intraday-ish interval among selected frames (default 15)."""
    mins = [TF_MINUTES[tf] for tf in timeframes if tf in TF_MINUTES]
    if not mins:
        return 15
    # Cap day/week so "match TF" does not sleep for a day when only 1d is selected
    # together with intraday — user can still pick custom minutes.
    intraday = [m for m in mins if m <= 240]
    return min(intraday or mins)


def resolve_interval_minutes(
    timeframes: list[str] | tuple[str, ...],
    *,
    mode: str = "match_tf",
    custom_minutes: int = 15,
) -> int:
    """
    mode:
      - match_tf: shortest selected timeframe
      - custom: user-chosen N minutes
    """
    if mode == "custom":
        return max(1, int(custom_minutes))
    return max(1, shortest_interval_minutes(timeframes))


def is_nse_session(now: datetime | None = None) -> bool:
    """True during NSE weekday cash hours (IST)."""
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)
    if now.weekday() >= 5:
        return False
    clock = now.time()
    return NSE_OPEN <= clock <= NSE_CLOSE


def seconds_until_due(
    last_finished_at: datetime | None,
    interval_minutes: int,
    *,
    now: datetime | None = None,
) -> float:
    """
    Seconds remaining until the next scan may start.

    Timer starts when the previous scan *finished* (avoids overlap when a full
    F&O pass takes longer than the timeframe).
    """
    now = now or datetime.now(IST)
    if last_finished_at is None:
        return 0.0
    last = last_finished_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=IST)
    elif now.tzinfo is not None:
        last = last.astimezone(now.tzinfo)
    due_at = last + timedelta(minutes=max(1, int(interval_minutes)))
    return max(0.0, (due_at - now).total_seconds())


def should_run_now(
    *,
    auto_enabled: bool,
    last_finished_at: datetime | None,
    interval_minutes: int,
    market_hours_only: bool,
    scan_running: bool,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """
    Decide whether to kick off a scan.

    Returns (should_run, reason_message).
    """
    now = now or datetime.now(IST)
    if not auto_enabled:
        return False, "Auto-scan off"
    if scan_running:
        return False, "Scan already running"
    if last_finished_at is None:
        return False, "Run one manual scan to arm auto-scan"
    if market_hours_only and not is_nse_session(now):
        return False, "Outside NSE market hours (auto-scan waiting)"
    wait = seconds_until_due(last_finished_at, interval_minutes, now=now)
    if wait > 0:
        return False, f"Next scan in {format_duration(wait)}"
    return True, "Due"


def format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def format_ist_clock(when: datetime | None = None) -> str:
    when = when or datetime.now(IST)
    if when.tzinfo is None:
        when = when.replace(tzinfo=IST)
    else:
        when = when.astimezone(IST)
    return when.strftime("%Y-%m-%d %H:%M:%S IST")
