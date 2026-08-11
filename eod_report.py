"""
End-of-day / scan report writers.

Saves generated BUY/SELL (and full scan) results under:
  reports/YYYY-MM-DD/
    eod_signals_15m.csv
    eod_mtf.csv
    eod_summary.txt
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from mtf import portfolio_metrics, summaries_to_frame

IST = ZoneInfo("Asia/Kolkata")


def report_dir(base: str | Path = "reports", when: datetime | None = None) -> Path:
    when = when or datetime.now(IST)
    path = Path(base) / when.strftime("%Y-%m-%d")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stamp(when: datetime | None = None) -> str:
    when = when or datetime.now(IST)
    return when.strftime("%Y-%m-%d %H:%M:%S IST")


def save_single_tf_eod(
    results: list[dict],
    *,
    interval: str,
    lookback: int,
    base_dir: str | Path = "reports",
    signal_only_file: bool = True,
) -> dict[str, Path]:
    """
    Write EOD artifacts for a single-timeframe F&O / watchlist scan.

    Returns paths of files written.
    """
    out_dir = report_dir(base_dir)
    stamp = _stamp()
    written: dict[str, Path] = {}

    df = pd.DataFrame(results)
    all_path = out_dir / f"eod_all_{interval}.csv"
    df.to_csv(all_path, index=False)
    written["all"] = all_path

    signals = [r for r in results if r.get("signal") in ("BUY", "SELL")]
    sig_path = out_dir / f"eod_signals_{interval}.csv"
    pd.DataFrame(signals).to_csv(sig_path, index=False)
    written["signals"] = sig_path

    buys = sum(1 for r in results if r.get("signal") == "BUY")
    sells = sum(1 for r in results if r.get("signal") == "SELL")
    building = sum(1 for r in results if r.get("signal") == "BUILDING")
    errors = sum(1 for r in results if r.get("signal") == "ERROR")
    none = len(results) - buys - sells - building - errors

    lines = [
        "AlphaTrend EOD Report (single timeframe)",
        f"Generated : {stamp}",
        f"Interval  : {interval}",
        f"Lookback  : {lookback} bar(s)",
        f"Symbols   : {len(results)}",
        "",
        "Counts",
        f"  BUY      : {buys}",
        f"  SELL     : {sells}",
        f"  NONE     : {none}",
        f"  BUILDING : {building}",
        f"  ERROR    : {errors}",
        "",
        "Signals",
    ]
    if not signals:
        lines.append("  (none)")
    else:
        for r in sorted(signals, key=lambda x: (x.get("signal", ""), x.get("symbol", ""))):
            lines.append(
                f"  {r.get('signal'):<4}  {r.get('symbol'):<14}  "
                f"close={r.get('close')}  AT={r.get('alphatrend')}  "
                f"trend={'UP' if r.get('trend_up') else 'DOWN'}  "
                f"bar_ago={r.get('bar_ago')}"
            )
    lines.append("")
    lines.append(f"Files: {all_path.name}, {sig_path.name}")

    summary_path = out_dir / f"eod_summary_{interval}.txt"
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    written["summary"] = summary_path
    return written


def save_mtf_eod(
    summaries: list[dict],
    frames: list[str],
    *,
    lookback: int,
    base_dir: str | Path = "reports",
) -> dict[str, Path]:
    """Write EOD artifacts for multi-timeframe scans."""
    out_dir = report_dir(base_dir)
    stamp = _stamp()
    written: dict[str, Path] = {}

    table = summaries_to_frame(summaries, frames)
    all_path = out_dir / "eod_mtf_all.csv"
    table.to_csv(all_path, index=False)
    written["all"] = all_path

    # Rows with any BUY/SELL on a timeframe
    active = [
        s
        for s in summaries
        if (s.get("buy_tf") or 0) > 0 or (s.get("sell_tf") or 0) > 0
    ]
    active_rows = []
    for s in active:
        row = {
            "symbol": s.get("symbol"),
            "mtf_score": s.get("mtf_score"),
            "bias": s.get("bias"),
            "alignment_pct": s.get("alignment_pct"),
            "buy_tf": s.get("buy_tf"),
            "sell_tf": s.get("sell_tf"),
            "avg_dist_pct": s.get("avg_dist_pct"),
            "close": s.get("close"),
        }
        tfs = s.get("timeframes") or {}
        for tf in frames:
            cell = tfs.get(tf) or {}
            row[f"{tf}_signal"] = cell.get("signal")
            row[f"{tf}_trend"] = (
                "UP" if cell.get("trend_up") else ("DOWN" if cell.get("trend_up") is False else None)
            )
        active_rows.append(row)

    sig_path = out_dir / "eod_mtf_signals.csv"
    pd.DataFrame(active_rows).to_csv(sig_path, index=False)
    written["signals"] = sig_path

    pm = portfolio_metrics(summaries)
    lines = [
        "AlphaTrend EOD Report (multi-timeframe)",
        f"Generated : {stamp}",
        f"Frames    : {', '.join(frames)}",
        f"Lookback  : {lookback} bar(s)",
        f"Symbols   : {len(summaries)}",
        "",
        "Desk numbers",
        f"  avg MTF score : {pm.get('avg_mtf_score')}",
        f"  breadth       : {pm.get('breadth')}%",
        f"  bull / bear / mixed : {pm.get('bull_count')} / {pm.get('bear_count')} / {pm.get('mixed_count')}",
        f"  BUY TFs       : {pm.get('buy_signals')}",
        f"  SELL TFs      : {pm.get('sell_signals')}",
        f"  building      : {pm.get('building')}",
        f"  errors        : {pm.get('errors')}",
        "",
        "Active signal symbols",
    ]
    if not active:
        lines.append("  (none)")
    else:
        for s in sorted(active, key=lambda x: (-(x.get("mtf_score") or 0), x.get("symbol") or "")):
            lines.append(
                f"  {s.get('symbol'):<14} score={s.get('mtf_score')}  bias={s.get('bias')}  "
                f"buyTF={s.get('buy_tf')} sellTF={s.get('sell_tf')}"
            )
    lines.append("")
    lines.append(f"Files: {all_path.name}, {sig_path.name}")

    summary_path = out_dir / "eod_mtf_summary.txt"
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    written["summary"] = summary_path
    return written
