#!/usr/bin/env python3
"""
AlphaTrend multi-symbol scanner (single-TF, multi-timeframe, NSE F&O modes).

Moto: scan NSE F&O equities and validate AlphaTrend signals on closed candles only.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from alphatrend import compute_alphatrend, latest_signal
from datafeed import (
    DEFAULT_MTF_FRAMES,
    INTERVAL_PERIOD,
    CLOSED_BAR_INTERVALS,
    drop_incomplete_bar,
    fetch_ohlcv,
    format_ist,
    history_status,
    min_bars_required,
    parse_symbols,
)
from mtf import portfolio_metrics, scan_universe_mtf, summaries_to_frame
from nse_fno import fno_yahoo_tickers, get_fno_symbols
from eod_report import save_mtf_eod, save_single_tf_eod


def scan_symbol(
    symbol: str,
    interval: str,
    period: str | None,
    multiplier: float,
    ap: int,
    no_volume: bool,
    lookback: int,
    *,
    include_forming: bool = False,
) -> dict:
    try:
        raw = fetch_ohlcv(symbol, interval, period, include_forming=True)
        dropped = False
        if include_forming or interval not in CLOSED_BAR_INTERVALS:
            df = raw
        else:
            df, dropped = drop_incomplete_bar(raw, interval)

        status = history_status(len(df), ap=ap, dropped_forming=dropped)
        if not status["ready"]:
            return {
                "symbol": symbol,
                "signal": "BUILDING",
                "bars": status["bars"],
                "bars_needed": status["bars_needed"],
                "dropped_forming": dropped,
                "error": status["message"],
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
            "signal_time": str(info["signal_time"]) if info.get("signal_time") is not None else None,
            "signal_time_ist": format_ist(info.get("signal_time")),
            "freshness": info.get("freshness"),
            "trend_since": str(info["trend_since"]) if info.get("trend_since") is not None else None,
            "trend_since_ist": format_ist(info.get("trend_since")),
            "trend_bars": info.get("trend_bars"),
            "close": info["close"],
            "alphatrend": info["alphatrend"],
            "trend_up": info["trend_up"],
            "price_vs_at": info["price_vs_at"],
            "last_bar": str(last_time),
            "last_bar_ist": format_ist(last_time),
            "bars": len(at),
            "bars_needed": min_bars_required(ap),
            "dropped_forming": dropped,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "symbol": symbol,
            "signal": "ERROR",
            "error": str(exc),
        }


def format_row(row: dict) -> str:
    if row["signal"] == "ERROR":
        return f"{row['symbol']:<14} ERROR     {row.get('error', '')}"
    if row["signal"] == "BUILDING":
        return (
            f"{row['symbol']:<14} BUILDING  "
            f"{row.get('error', '')}"
        )

    sig = row["signal"]
    trend = "UP" if row.get("trend_up") else "DOWN"
    bar = "" if row.get("bar_ago") is None else f"  ({row['bar_ago']} bar(s) ago)"
    fresh = row.get("freshness")
    if fresh == "NEW":
        bar = "  [NEW]"
    elif fresh and row.get("bar_ago") is not None:
        bar = f"  ({fresh})"
    at = row.get("alphatrend")
    close = row.get("close")
    pva = row.get("price_vs_at") or "-"
    at_s = f"{at:.4f}" if at is not None else "n/a"
    close_s = f"{close:.4f}" if close is not None else "n/a"
    closed = " closed" if row.get("dropped_forming") else ""
    when = row.get("signal_time_ist") or ""
    when_s = f"  @ {when}" if when else ""
    return (
        f"{row['symbol']:<14} {sig:<5}  trend={trend:<4}  "
        f"price={close_s:>10}  AT={at_s:>10}  vs_AT={pva:<5}{bar}{when_s}{closed}"
    )


def format_mtf_row(row: dict, frames: list[str]) -> str:
    if row.get("bias") in ("ERROR", "BUILDING"):
        return f"{row['symbol']:<14} {row.get('bias'):<8}  {row.get('error', '')}"

    score = row.get("mtf_score")
    score_s = f"{score:+6.1f}" if score is not None else "   n/a"
    align = row.get("alignment_pct")
    align_s = f"{align:5.1f}%" if align is not None else "  n/a"
    dist = row.get("avg_dist_pct")
    dist_s = f"{dist:+6.2f}%" if dist is not None else "   n/a"

    tf_bits = []
    tfs = row.get("timeframes") or {}
    for tf in frames:
        cell = tfs.get(tf) or {}
        sig = cell.get("signal")
        if sig == "ERROR":
            mark = "E"
        elif sig == "BUILDING":
            mark = "H"  # history building
        elif cell.get("trend_up") is None:
            mark = "?"
        elif sig == "BUY":
            mark = "B"
        elif sig == "SELL":
            mark = "S"
        else:
            mark = "↑" if cell.get("trend_up") else "↓"
        tf_bits.append(f"{tf}:{mark}")

    return (
        f"{row['symbol']:<14} score={score_s}  bias={row.get('bias', '?'):<5}  "
        f"align={align_s}  dist={dist_s}  "
        f"bull={row.get('bull_tf', 0)} bear={row.get('bear_tf', 0)}  "
        f"buyTF={row.get('buy_tf', 0)} sellTF={row.get('sell_tf', 0)}  "
        + " ".join(tf_bits)
    )


def resolve_symbols(args) -> list[str]:
    if args.fno:
        tickers = fno_yahoo_tickers(
            refresh=args.refresh_fno,
            include_indices=args.fno_indices,
        )
        if args.limit and args.limit > 0:
            tickers = tickers[: args.limit]
        return tickers
    return parse_symbols(args.symbols, args.file)


def run_single_tf(args, symbols: list[str]) -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode = "forming" if args.include_forming else "closed-bars"
    print(
        f"AlphaTrend Scanner  |  {now}  |  interval={args.interval}  "
        f"coeff={args.multiplier}  AP={args.ap}  lookback={args.lookback}  "
        f"gate={'RSI' if args.no_volume else 'MFI'}  bars={mode}"
    )
    print(f"Symbols: {len(symbols)}" + ("  [NSE F&O]" if args.fno else ""))
    print("-" * 100)

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
                include_forming=args.include_forming,
            ): sym
            for sym in symbols
        }
        for fut in as_completed(futures):
            results.append(fut.result())

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
    building = sum(1 for r in results if r["signal"] == "BUILDING")
    errors = sum(1 for r in results if r["signal"] == "ERROR")
    print("-" * 100)
    print(
        f"Done. BUY={buys}  SELL={sells}  "
        f"NONE/other={len(results) - buys - sells - building - errors}  "
        f"BUILDING={building}  ERROR={errors}"
    )

    if args.csv:
        pd.DataFrame(results).to_csv(args.csv, index=False)
        print(f"Wrote {args.csv}")

    if args.eod:
        paths = save_single_tf_eod(
            results,
            interval=args.interval,
            lookback=args.lookback,
            base_dir=args.reports_dir,
        )
        print("EOD report saved:")
        for kind, path in paths.items():
            print(f"  {kind}: {path}")

    return 0 if errors == 0 else 1


def run_mtf(args, symbols: list[str]) -> int:
    frames = [f.strip() for f in args.mtf_frames.split(",") if f.strip()]
    if not frames:
        frames = list(DEFAULT_MTF_FRAMES)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode = "forming" if args.include_forming else "closed-bars"
    print(
        f"AlphaTrend MTF Scanner  |  {now}  |  frames={','.join(frames)}  "
        f"coeff={args.multiplier}  AP={args.ap}  lookback={args.lookback}  "
        f"gate={'RSI' if args.no_volume else 'MFI'}  bars={mode}"
    )
    print(f"Symbols: {len(symbols)}" + ("  [NSE F&O]" if args.fno else ""))
    print("-" * 110)

    summaries = scan_universe_mtf(
        symbols,
        timeframes=frames,
        multiplier=args.multiplier,
        ap=args.ap,
        no_volume=args.no_volume,
        lookback=args.lookback,
        workers=args.workers,
        include_forming=args.include_forming,
    )

    shown = 0
    for row in summaries:
        if args.signal_only and row.get("buy_tf", 0) == 0 and row.get("sell_tf", 0) == 0:
            continue
        if args.mtf_min_score is not None and (
            row.get("mtf_score") is None or abs(row["mtf_score"]) < args.mtf_min_score
        ):
            continue
        print(format_mtf_row(row, frames))
        shown += 1

    if shown == 0:
        print("(no rows matched filters)")

    pm = portfolio_metrics(summaries)
    building = sum(1 for r in summaries if r.get("bias") == "BUILDING")
    errors = sum(1 for r in summaries if r.get("bias") == "ERROR")
    print("-" * 110)
    print(
        f"Desk numbers  avg_score={pm['avg_mtf_score']}  breadth={pm['breadth']}%  "
        f"bull={pm['bull_count']} bear={pm['bear_count']} mixed={pm['mixed_count']}  "
        f"BUY_TFs={pm['buy_signals']} SELL_TFs={pm['sell_signals']}  "
        f"avg_align={pm['avg_alignment_pct']}%  avg_dist={pm['avg_dist_pct']}%  "
        f"BUILDING={building} ERROR={errors}"
    )

    if args.csv:
        summaries_to_frame(summaries, frames).to_csv(args.csv, index=False)
        print(f"Wrote {args.csv}")

    if args.eod:
        paths = save_mtf_eod(
            summaries,
            frames,
            lookback=args.lookback,
            base_dir=args.reports_dir,
        )
        print("EOD report saved:")
        for kind, path in paths.items():
            print(f"  {kind}: {path}")

    return 0 if errors == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scan symbols for AlphaTrend BUY/SELL signals. "
            "Use --fno to validate signals across all NSE F&O equities."
        ),
    )
    parser.add_argument("--symbols", "-s", help="Comma-separated tickers")
    parser.add_argument("--file", "-f", help="Path to a file with one ticker per line")
    parser.add_argument(
        "--fno",
        action="store_true",
        help="Scan all NSE F&O equity underlyings (Yahoo SYMBOL.NS)",
    )
    parser.add_argument(
        "--refresh-fno",
        action="store_true",
        help="Force refresh of the NSE F&O list cache",
    )
    parser.add_argument(
        "--fno-indices",
        action="store_true",
        help="Include index underlyings (NIFTY, BANKNIFTY, …) with --fno",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on symbol count (useful for smoke tests)",
    )
    parser.add_argument(
        "--interval",
        "-i",
        default="15m",
        choices=sorted(INTERVAL_PERIOD.keys()),
        help="Bar interval for single-TF mode (default: 15m for F&O validation)",
    )
    parser.add_argument("--period", "-p", default=None, help="yfinance history period override")
    parser.add_argument("--multiplier", "-m", type=float, default=1.0, help="AlphaTrend coeff")
    parser.add_argument("--period-ap", "--ap", dest="ap", type=int, default=14, help="Common period AP")
    parser.add_argument("--no-volume", action="store_true", help="Use RSI gate instead of MFI")
    parser.add_argument("--lookback", "-l", type=int, default=3, help="Signal lookback in bars")
    parser.add_argument("--signal-only", action="store_true", help="Only print active signal rows")
    parser.add_argument("--workers", type=int, default=6, help="Parallel workers")
    parser.add_argument("--csv", help="Optional CSV output path")
    parser.add_argument(
        "--eod",
        action="store_true",
        help="Save EOD report under reports/YYYY-MM-DD/ (CSV + summary txt)",
    )
    parser.add_argument(
        "--reports-dir",
        default="reports",
        help="Base folder for --eod reports (default: reports)",
    )
    parser.add_argument(
        "--include-forming",
        action="store_true",
        help=(
            "Live-but-unconfirmed read: include the in-progress 5m/15m/1h bar. "
            "Default is closed-bars only (no flicker)."
        ),
    )

    parser.add_argument("--mtf", action="store_true", help="Multi-timeframe confluence mode")
    parser.add_argument(
        "--mtf-frames",
        default=",".join(DEFAULT_MTF_FRAMES),
        help="Comma-separated frames for --mtf (default: 5m,15m,1h,4h,1d,1wk)",
    )
    parser.add_argument(
        "--mtf-min-score",
        type=float,
        default=None,
        help="Only show symbols with |mtf_score| >= this value",
    )
    parser.add_argument(
        "--list-fno",
        action="store_true",
        help="Print NSE F&O symbols and exit",
    )
    args = parser.parse_args(argv)

    if args.list_fno:
        rows = get_fno_symbols(refresh=args.refresh_fno, include_indices=args.fno_indices)
        for r in rows:
            print(f"{r['symbol']:<14} {r['yf_symbol']:<22} {r.get('underlying', '')}")
        print(f"Total: {len(rows)}")
        return 0

    symbols = resolve_symbols(args)
    if not symbols:
        print("No symbols to scan.", file=sys.stderr)
        return 2

    if args.mtf:
        return run_mtf(args, symbols)
    return run_single_tf(args, symbols)


if __name__ == "__main__":
    sys.exit(main())
