#!/usr/bin/env python3
"""
AlphaTrend multi-symbol scanner (single-TF and multi-timeframe modes).
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from alphatrend import compute_alphatrend, latest_signal
from datafeed import DEFAULT_MTF_FRAMES, INTERVAL_PERIOD, fetch_ohlcv, parse_symbols
from mtf import portfolio_metrics, scan_universe_mtf, summaries_to_frame


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
    except Exception as exc:  # noqa: BLE001
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


def format_mtf_row(row: dict, frames: list[str]) -> str:
    if row.get("bias") == "ERROR":
        return f"{row['symbol']:<8} ERROR  {row.get('error', '')}"

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
        if cell.get("signal") == "ERROR" or cell.get("trend_up") is None:
            mark = "?"
        elif cell.get("signal") == "BUY":
            mark = "B"
        elif cell.get("signal") == "SELL":
            mark = "S"
        else:
            mark = "↑" if cell.get("trend_up") else "↓"
        tf_bits.append(f"{tf}:{mark}")

    return (
        f"{row['symbol']:<8} score={score_s}  bias={row.get('bias', '?'):<5}  "
        f"align={align_s}  dist={dist_s}  "
        f"bull={row.get('bull_tf', 0)} bear={row.get('bear_tf', 0)}  "
        f"buyTF={row.get('buy_tf', 0)} sellTF={row.get('sell_tf', 0)}  "
        + " ".join(tf_bits)
    )


def run_single_tf(args, symbols: list[str]) -> int:
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
    print(
        f"Done. BUY={buys}  SELL={sells}  "
        f"NONE/other={len(results) - buys - sells - errors}  ERROR={errors}"
    )

    if args.csv:
        pd.DataFrame(results).to_csv(args.csv, index=False)
        print(f"Wrote {args.csv}")

    return 0 if errors == 0 else 1


def run_mtf(args, symbols: list[str]) -> int:
    frames = [f.strip() for f in args.mtf_frames.split(",") if f.strip()]
    if not frames:
        frames = list(DEFAULT_MTF_FRAMES)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(
        f"AlphaTrend MTF Scanner  |  {now}  |  frames={','.join(frames)}  "
        f"coeff={args.multiplier}  AP={args.ap}  lookback={args.lookback}  "
        f"gate={'RSI' if args.no_volume else 'MFI'}"
    )
    print(f"Symbols: {len(symbols)}")
    print("-" * 100)

    summaries = scan_universe_mtf(
        symbols,
        timeframes=frames,
        multiplier=args.multiplier,
        ap=args.ap,
        no_volume=args.no_volume,
        lookback=args.lookback,
        workers=args.workers,
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
    print("-" * 100)
    print(
        f"Desk numbers  avg_score={pm['avg_mtf_score']}  breadth={pm['breadth']}%  "
        f"bull={pm['bull_count']} bear={pm['bear_count']} mixed={pm['mixed_count']}  "
        f"BUY_TFs={pm['buy_signals']} SELL_TFs={pm['sell_signals']}  "
        f"avg_align={pm['avg_alignment_pct']}%  avg_dist={pm['avg_dist_pct']}%"
    )

    if args.csv:
        summaries_to_frame(summaries, frames).to_csv(args.csv, index=False)
        print(f"Wrote {args.csv}")

    errors = sum(1 for r in summaries if r.get("bias") == "ERROR")
    return 0 if errors == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan symbols for AlphaTrend BUY/SELL signals (single-TF or multi-TF).",
    )
    parser.add_argument("--symbols", "-s", help="Comma-separated tickers")
    parser.add_argument("--file", "-f", help="Path to a file with one ticker per line")
    parser.add_argument(
        "--interval",
        "-i",
        default="1d",
        choices=sorted(INTERVAL_PERIOD.keys()),
        help="Bar interval for single-TF mode (default: 1d)",
    )
    parser.add_argument("--period", "-p", default=None, help="yfinance history period override")
    parser.add_argument("--multiplier", "-m", type=float, default=1.0, help="AlphaTrend coeff")
    parser.add_argument("--period-ap", "--ap", dest="ap", type=int, default=14, help="Common period AP")
    parser.add_argument("--no-volume", action="store_true", help="Use RSI gate instead of MFI")
    parser.add_argument("--lookback", "-l", type=int, default=1, help="Signal lookback in bars")
    parser.add_argument("--signal-only", action="store_true", help="Only print active signal rows")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers")
    parser.add_argument("--csv", help="Optional CSV output path")

    parser.add_argument(
        "--mtf",
        action="store_true",
        help="Multi-timeframe mode (confluence score across frames)",
    )
    parser.add_argument(
        "--mtf-frames",
        default=",".join(DEFAULT_MTF_FRAMES),
        help="Comma-separated frames for --mtf (default: 15m,1h,4h,1d,1wk)",
    )
    parser.add_argument(
        "--mtf-min-score",
        type=float,
        default=None,
        help="Only show symbols with |mtf_score| >= this value",
    )
    args = parser.parse_args(argv)
    symbols = parse_symbols(args.symbols, args.file)

    if args.mtf:
        # MTF default lookback 3 is more useful; keep user value if they set -l
        if args.lookback == 1 and (argv is None or "-l" not in argv and "--lookback" not in (argv or [])):
            # When called programmatically with defaults, bump lookback for MTF
            pass
        return run_mtf(args, symbols)
    return run_single_tf(args, symbols)


if __name__ == "__main__":
    sys.exit(main())
