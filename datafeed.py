"""Shared OHLCV fetch helpers for scanner and dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

IST = ZoneInfo("Asia/Kolkata")


def format_ist(ts) -> str | None:
    """Format a candle timestamp as IST for desk display / CSV."""
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return None
    try:
        stamp = pd.Timestamp(ts)
    except (ValueError, TypeError):
        return str(ts)
    if pd.isna(stamp):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(IST)
    else:
        stamp = stamp.tz_convert(IST)
    return stamp.strftime("%Y-%m-%d %H:%M IST")


def bare_ticker(symbol: str) -> str:
    """RELIANCE.NS → RELIANCE (easy to paste into a broker)."""
    s = (symbol or "").strip().upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return s[:-3]
    return s

DEFAULT_SYMBOLS = [
    "RELIANCE.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "INFY.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "ITC.NS",
    "LT.NS",
    "KOTAKBANK.NS",
]

# yfinance period caps — stay safely inside Yahoo limits.
# Note: period="730d" for 1h often errors ("must be within the last 730 days").
INTERVAL_PERIOD = {
    "5m": "60d",
    "15m": "60d",
    "1h": "365d",
    "4h": "365d",
    "1d": "2y",
    "1wk": "5y",
}

# Bar duration used to decide whether the last candle is still forming.
INTERVAL_DELTA = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "60m": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "1wk": timedelta(days=7),
}

# Intraday intervals where evaluating a still-forming bar creates flicker.
CLOSED_BAR_INTERVALS = frozenset({"5m", "15m", "1h", "60m", "4h"})

DEFAULT_MTF_FRAMES = ("5m", "15m", "1h", "4h", "1d", "1wk")

# AlphaTrend needs AP bars for ATR/MFI plus a couple for AT[2] crosses.
MIN_BARS_PADDING = 5


def parse_symbols(raw: str | None, file_path: str | None) -> list[str]:
    symbols: list[str] = []
    if file_path:
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    symbols.append(line.upper())
    if raw:
        symbols.extend(s.strip().upper() for s in raw.split(",") if s.strip())
    if not symbols:
        symbols = list(DEFAULT_SYMBOLS)
    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            out.append(normalize_symbol(s))
    return out


def normalize_symbol(symbol: str) -> str:
    """
    Accept RELIANCE, RELIANCE.NS, or already-qualified Yahoo tickers.
    Bare NSE cash symbols become SYMBOL.NS.
    """
    s = symbol.strip().upper()
    if not s:
        return s
    if s.startswith("^"):
        return s
    if "." in s:
        return s
    # Heuristic: plain equity tickers without exchange suffix → NSE
    return f"{s}.NS"


def ensure_datetime_index(df: pd.DataFrame, *, assume_tz: str = "Asia/Kolkata") -> pd.DataFrame:
    """
    Guarantee a DatetimeIndex before resample / closed-bar checks.

    Without this, pandas raises:
      Only valid with DatetimeIndex, TimedeltaIndex or PeriodIndex,
      but got an instance of 'Index'
    when the feed returns plain/string timestamps (common after CSV/API joins).
    """
    if df.empty:
        return df

    out = df.copy()

    # If Datetime landed as a column (e.g. reset_index upstream), put it back.
    for candidate in ("Datetime", "datetime", "Date", "date", "timestamp", "Timestamp"):
        if candidate in out.columns and not isinstance(out.index, pd.DatetimeIndex):
            out = out.set_index(candidate)
            break

    if not isinstance(out.index, pd.DatetimeIndex):
        converted = pd.to_datetime(out.index, utc=False, errors="coerce")
        if converted.isna().all():
            raise TypeError(
                "Candle index is not datetime-like; cannot build AlphaTrend history "
                f"(got {type(out.index).__name__})"
            )
        out = out.copy()
        out.index = converted
        out = out[~out.index.isna()]

    if not isinstance(out.index, pd.DatetimeIndex):
        raise TypeError(
            "Only valid with DatetimeIndex after normalization, "
            f"but got {type(out.index).__name__}"
        )

    # NSE intraday bars should be timezone-aware for closed-bar math.
    if out.index.tz is None:
        try:
            out.index = out.index.tz_localize(ZoneInfo(assume_tz))
        except Exception:
            # Fall back to UTC if localize conflicts (already-ambiguous stamps)
            out.index = out.index.tz_localize(timezone.utc)

    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def bar_is_closed(
    bar_start: pd.Timestamp,
    interval: str,
    now: datetime | None = None,
) -> bool:
    """True when the candle that started at bar_start has fully finished."""
    delta = INTERVAL_DELTA.get(interval)
    if delta is None:
        return True

    ts = pd.Timestamp(bar_start)
    if ts.tzinfo is None:
        # NSE equity bars from yfinance are usually Asia/Kolkata; assume that
        # for .NS context, otherwise UTC.
        ts = ts.tz_localize(ZoneInfo("Asia/Kolkata"))

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_aware = pd.Timestamp(now).tz_convert(ts.tzinfo)
    return now_aware >= (ts + delta)


def drop_incomplete_bar(
    df: pd.DataFrame,
    interval: str,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, bool]:
    """
    Drop the last row when it is still forming.

    Returns (frame, dropped_flag).

    Practice:
      5m / 15m / 1h / 4h signals only ever evaluate against fully-closed bars —
      no early flickers that vanish once the bar finishes forming.

    Side effect: "building history" bar counts grow by one slightly slower near
    each boundary (the in-progress bar simply won't count until it closes).

    For a live-but-unconfirmed read, call fetch_ohlcv(..., include_forming=True)
    or skip this helper.
    """
    if df.empty or interval not in CLOSED_BAR_INTERVALS:
        return df, False
    df = ensure_datetime_index(df)
    last_ts = df.index[-1]
    if bar_is_closed(last_ts, interval, now=now):
        return df, False
    return df.iloc[:-1].copy(), True


def min_bars_required(ap: int = 14) -> int:
    return int(ap) + MIN_BARS_PADDING


def fetch_ohlcv(
    symbol: str,
    interval: str,
    period: str | None = None,
    *,
    include_forming: bool = False,
    now: datetime | None = None,
) -> pd.DataFrame:
    """
    Download OHLCV; resample 1h→4h when interval is 4h.

    By default, incomplete intraday bars are dropped (closed-bar mode).
    Pass include_forming=True for the earlier live-but-unconfirmed read.
    """
    import logging
    import warnings

    symbol = normalize_symbol(symbol)
    yf_interval = "1h" if interval == "4h" else interval
    yf_period = period or INTERVAL_PERIOD.get(interval, "6mo")

    # Quiet Yahoo "Failed download / possibly delisted" spam in MTF scans
    yf_logger = logging.getLogger("yfinance")
    prev_level = yf_logger.level
    yf_logger.setLevel(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            data = yf.download(
                symbol,
                period=yf_period,
                interval=yf_interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
    finally:
        yf_logger.setLevel(prev_level)

    if data.empty:
        raise RuntimeError(f"No data returned for {symbol} ({interval}, period={yf_period})")

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [c[0] for c in data.columns]

    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data = data[cols].dropna(how="all")
    data = data.dropna(subset=["Close"])
    # Critical: normalize BEFORE resample / closed-bar drop so we never hit
    # "Only valid with DatetimeIndex ... got an instance of 'Index'".
    data = ensure_datetime_index(data)

    if interval == "4h":
        ohlc = {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
        data = data.resample("4h").agg({k: v for k, v in ohlc.items() if k in data.columns})
        data = data.dropna(subset=["Close"])
        data = ensure_datetime_index(data)

    if not include_forming:
        data, _ = drop_incomplete_bar(data, interval, now=now)

    if data.empty:
        raise RuntimeError(
            f"No closed bars yet for {symbol} ({interval}) — still building history"
        )

    return data


def history_status(bar_count: int, ap: int = 14, dropped_forming: bool = False) -> dict:
    """Explain whether AlphaTrend has enough closed history to validate a signal."""
    need = min_bars_required(ap)
    ready = bar_count >= need
    return {
        "bars": bar_count,
        "bars_needed": need,
        "ready": ready,
        "dropped_forming": dropped_forming,
        "message": (
            None
            if ready
            else (
                f"Building history: need {need} closed bars, have {bar_count}"
                + (" (in-progress bar excluded)" if dropped_forming else "")
            )
        ),
    }
