#!/usr/bin/env python3
"""
AlphaTrend multi-symbol scanner.

Fetches OHLCV via yfinance, computes AlphaTrend (Pine Script port),
and reports BUY / SELL / trend state for each symbol.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from alphatrend import compute_alphatrend, latest_signal

# Sensible default watchlist (US equities + liquid ETFs). Override with --symbols.
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
    "1d": "6mo",
    "1h": "60d",
    "4h": "60d",  # yfinance has no native 4h; resampled from 1h
    "1wk": "2y",
    "15m": "60d",
    "5m": "60d",
}


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
    # de-dupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def fetch_ohlcv(symbol: str, interval: str, period: str | None) -> pd.DataFrame:
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

    # yfinance may return MultiIndex columns for a single ticker
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [c[0] for c in data.columns]

    data = data.rename(
        columns={
            "Open": "Open",
            "High": "High",
            "Low": "Low",
            "Close": "Close",
            "Volume": "Volume",
        }
    )
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


def scan_symbol(
    symbol: str,
    interval: str,
    period: str | None,
    multiplier: float,
    ap: int,
    no_volume: bool,
    lookback: int,
) -> dict:
    try:
        df = fetch_ohlcv(symbol, interval, period)
        if len(df) < ap + 5:
            return {
                "symbol": symbol,
                "signal": "ERROR",
                "error": f"Insufficient bars ({len(df)})",
            }
        at = compute_alphatrend(
            df,
            multiplier=multiplier,
            period=ap,
            no_volume_data=no_volume,
        )
        info = latest_signal(at, lookback=lookback)
        last_time = at.index[-1]
        return {
            "symbol": symbol,
            "signal": info["signal"],
            "bar_ago": info["bar_ago"],
            "close": info["close"],
            "alphatrend": info["alphatrend"],
            "trend_up": info["trend_up"],
            "price_vs_at": info["price_vs_at"],
            "last_bar": str(last_time),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — scanner must keep going
        return {
            "symbol": symbol,
            "signal": "ERROR",
            "error": str(exc),
        }


def format_row(row: dict) -> str:
    if row["signal"] == "ERROR":
        return f"{row['symbol']:<8} ERROR  {row.get('error', '')}"

    sig = row["signal"]
    trend = "UP" if row.get("trend_up") else "DOWN"
    bar = "" if row.get("bar_ago") is None else f"  ({row['bar_ago']} bar(s) ago)"
    at = row.get("alphatrend")
    close = row.get("close")
    pva = row.get("price_vs_at") or "-"
    at_s = f"{at:.4f}" if at is not None else "n/a"
    close_s = f"{close:.4f}" if close is not None else "n/a"
    return (
        f"{row['symbol']:<8} {sig:<5}  trend={trend:<4}  "
        f"price={close_s:>10}  AT={at_s:>10}  vs_AT={pva:<5}{bar}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan symbols for AlphaTrend BUY/SELL signals (TradingView Pine port).",
    )
    parser.add_argument(
        "--symbols",
        "-s",
        help="Comma-separated tickers (default: built-in US mega-cap list)",
    )
    parser.add_argument(
        "--file",
        "-f",
        help="Path to a file with one ticker per line",
    )
    parser.add_argument(
        "--interval",
        "-i",
        default="1d",
        choices=sorted(INTERVAL_PERIOD.keys()),
        help="Bar interval (default: 1d)",
    )
    parser.add_argument(
        "--period",
        "-p",
        default=None,
        help="yfinance history period override (e.g. 1y, 6mo, 60d)",
    )
    parser.add_argument(
        "--multiplier",
        "-m",
        type=float,
        default=1.0,
        help="AlphaTrend multiplier / coeff (default: 1.0)",
    )
    parser.add_argument(
        "--period-ap",
        "--ap",
        dest="ap",
        type=int,
        default=14,
        help="Common period AP for ATR/MFI/RSI (default: 14)",
    )
    parser.add_argument(
        "--no-volume",
        action="store_true",
        help="Use RSI gate instead of MFI (Pine 'novolumedata')",
    )
    parser.add_argument(
        "--lookback",
        "-l",
        type=int,
        default=1,
        help="Signal lookback in bars (1 = last bar only / confirmed-style)",
    )
    parser.add_argument(
        "--signal-only",
        action="store_true",
        help="Only print symbols with BUY or SELL in the lookback window",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Parallel download workers (default: 4)",
    )
    parser.add_argument(
        "--csv",
        help="Optional path to write full results as CSV",
    )
    args = parser.parse_args(argv)

    symbols = parse_symbols(args.symbols, args.file)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(
        f"AlphaTrend Scanner  |  {now}  |  interval={args.interval}  "
        f"coeff={args.multiplier}  AP={args.ap}  lookback={args.lookback}  "
        f"gate={'RSI' if args.no_volume else 'MFI'}"
    )
    print(f"Symbols: {len(symbols)}")
    print("-" * 88)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                scan_symbol,
                sym,
                args.interval,
                args.period,
                args.multiplier,
                args.ap,
                args.no_volume,
                args.lookback,
            ): sym
            for sym in symbols
        }
        for fut in as_completed(futures):
            results.append(fut.result())

    # Stable order matching input list
    order = {s: i for i, s in enumerate(symbols)}
    results.sort(key=lambda r: order.get(r["symbol"], 9999))

    shown = 0
    for row in results:
        if args.signal_only and row["signal"] not in ("BUY", "SELL"):
            continue
        print(format_row(row))
        shown += 1

    if args.signal_only and shown == 0:
        print("(no BUY/SELL signals in lookback window)")

    buys = sum(1 for r in results if r["signal"] == "BUY")
    sells = sum(1 for r in results if r["signal"] == "SELL")
    errors = sum(1 for r in results if r["signal"] == "ERROR")
    print("-" * 88)
    print(f"Done. BUY={buys}  SELL={sells}  NONE/other={len(results) - buys - sells - errors}  ERROR={errors}")

    if args.csv:
        pd.DataFrame(results).to_csv(args.csv, index=False)
        print(f"Wrote {args.csv}")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
