"""Shared OHLCV fetch helpers for scanner and dashboard."""

from __future__ import annotations

import pandas as pd
import yfinance as yf

DEFAULT_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
    "AMD",
    "NFLX",
    "SPY",
    "QQQ",
    "IWM",
]

INTERVAL_PERIOD = {
    "5m": "60d",
    "15m": "60d",
    "1h": "60d",
    "4h": "60d",
    "1d": "1y",
    "1wk": "5y",
}

DEFAULT_MTF_FRAMES = ("15m", "1h", "4h", "1d", "1wk")


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
            out.append(s)
    return out


def fetch_ohlcv(symbol: str, interval: str, period: str | None = None) -> pd.DataFrame:
    """Download OHLCV; resample 1h→4h when interval is 4h."""
    yf_interval = "1h" if interval == "4h" else interval
    yf_period = period or INTERVAL_PERIOD.get(interval, "6mo")

    data = yf.download(
        symbol,
        period=yf_period,
        interval=yf_interval,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if data.empty:
        raise RuntimeError(f"No data returned for {symbol}")

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [c[0] for c in data.columns]

    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data = data[cols].dropna(how="all")

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

    return data
