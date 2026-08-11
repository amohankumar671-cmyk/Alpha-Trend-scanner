"""
Multi-timeframe AlphaTrend analysis.

Scores each symbol across several chart intervals and produces
confluence metrics used by the CLI scanner and the dashboard.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

import pandas as pd

from alphatrend import compute_alphatrend, latest_signal
from datafeed import DEFAULT_MTF_FRAMES, fetch_ohlcv

# Higher timeframes weigh more in the confluence score.
TF_WEIGHTS: dict[str, float] = {
    "5m": 0.75,
    "15m": 1.0,
    "1h": 1.5,
    "4h": 2.0,
    "1d": 2.5,
    "1wk": 3.0,
}


def _distance_pct(close: float | None, alphatrend: float | None) -> float | None:
    if close is None or alphatrend is None or alphatrend == 0:
        return None
    return ((close - alphatrend) / alphatrend) * 100.0


def analyze_timeframe(
    symbol: str,
    interval: str,
    multiplier: float = 1.0,
    ap: int = 14,
    no_volume: bool = False,
    lookback: int = 3,
    period: str | None = None,
) -> dict:
    """Run AlphaTrend on one symbol/interval and return metric row."""
    try:
        df = fetch_ohlcv(symbol, interval, period)
        if len(df) < ap + 5:
            return {
                "symbol": symbol,
                "interval": interval,
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
        last = at.iloc[-1]
        atr = float(last["ATR"]) if pd.notna(last.get("ATR")) else None
        dist = _distance_pct(info["close"], info["alphatrend"])
        atr_pct = None
        if atr is not None and info["close"]:
            atr_pct = (atr / info["close"]) * 100.0

        return {
            "symbol": symbol,
            "interval": interval,
            "signal": info["signal"],
            "bar_ago": info["bar_ago"],
            "close": info["close"],
            "alphatrend": info["alphatrend"],
            "trend_up": info["trend_up"],
            "price_vs_at": info["price_vs_at"],
            "dist_pct": dist,
            "atr": atr,
            "atr_pct": atr_pct,
            "last_bar": str(at.index[-1]),
            "bars": len(at),
            "error": None,
            "series": at,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "symbol": symbol,
            "interval": interval,
            "signal": "ERROR",
            "error": str(exc),
        }


def _tf_signed_score(row: dict, weight: float) -> float:
    """Map one TF snapshot to a weighted contribution toward confluence."""
    if row.get("signal") == "ERROR" or row.get("trend_up") is None:
        return 0.0

    trend = 1.0 if row["trend_up"] else -1.0
    price_align = 0.0
    if row.get("price_vs_at") == "ABOVE":
        price_align = 0.35
    elif row.get("price_vs_at") == "BELOW":
        price_align = -0.35

    signal_boost = 0.0
    if row.get("signal") == "BUY":
        signal_boost = 0.5
    elif row.get("signal") == "SELL":
        signal_boost = -0.5

    return weight * (trend + price_align + signal_boost)


def summarize_mtf(tf_rows: list[dict]) -> dict:
    """
    Collapse per-timeframe rows into one symbol summary with new metric numbers.

    Numbers produced:
      - mtf_score      : -100 .. +100 confluence (weighted)
      - alignment_pct  : % of valid TFs that are trend-up
      - bull_tf / bear_tf
      - buy_tf / sell_tf (signals in lookback)
      - avg_dist_pct   : mean distance of price vs AlphaTrend
      - bias           : BULL / BEAR / MIXED
    """
    valid = [r for r in tf_rows if r.get("signal") != "ERROR" and r.get("trend_up") is not None]
    symbol = tf_rows[0]["symbol"] if tf_rows else "?"
    if not valid:
        return {
            "symbol": symbol,
            "mtf_score": None,
            "alignment_pct": None,
            "bull_tf": 0,
            "bear_tf": 0,
            "buy_tf": 0,
            "sell_tf": 0,
            "avg_dist_pct": None,
            "bias": "ERROR",
            "tf_count": 0,
            "error": "; ".join(r.get("error") or "error" for r in tf_rows),
            "timeframes": {r["interval"]: r for r in tf_rows},
        }

    bull = sum(1 for r in valid if r["trend_up"])
    bear = len(valid) - bull
    buy_tf = sum(1 for r in valid if r.get("signal") == "BUY")
    sell_tf = sum(1 for r in valid if r.get("signal") == "SELL")
    dists = [r["dist_pct"] for r in valid if r.get("dist_pct") is not None]
    avg_dist = sum(dists) / len(dists) if dists else None

    raw = 0.0
    max_abs = 0.0
    for r in valid:
        w = TF_WEIGHTS.get(r["interval"], 1.0)
        # theoretical max magnitude per TF ≈ weight * (1 + 0.35 + 0.5)
        max_abs += w * 1.85
        raw += _tf_signed_score(r, w)

    mtf_score = round(100.0 * raw / max_abs, 1) if max_abs else 0.0
    alignment_pct = round(100.0 * bull / len(valid), 1)

    if mtf_score >= 25:
        bias = "BULL"
    elif mtf_score <= -25:
        bias = "BEAR"
    else:
        bias = "MIXED"

    # strip heavy series from nested dict used in tables
    light_tfs = {}
    for r in tf_rows:
        light = {k: v for k, v in r.items() if k != "series"}
        light_tfs[r["interval"]] = light

    return {
        "symbol": symbol,
        "mtf_score": mtf_score,
        "alignment_pct": alignment_pct,
        "bull_tf": bull,
        "bear_tf": bear,
        "buy_tf": buy_tf,
        "sell_tf": sell_tf,
        "avg_dist_pct": round(avg_dist, 3) if avg_dist is not None else None,
        "bias": bias,
        "tf_count": len(valid),
        "close": valid[-1].get("close"),  # prefer highest TF order later
        "error": None,
        "timeframes": light_tfs,
        "_raw_rows": tf_rows,
    }


def analyze_symbol_mtf(
    symbol: str,
    timeframes: Iterable[str] = DEFAULT_MTF_FRAMES,
    multiplier: float = 1.0,
    ap: int = 14,
    no_volume: bool = False,
    lookback: int = 3,
    workers: int = 4,
) -> dict:
    frames = list(timeframes)
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(frames) or 1))) as pool:
        futs = {
            pool.submit(
                analyze_timeframe,
                symbol,
                tf,
                multiplier,
                ap,
                no_volume,
                lookback,
            ): tf
            for tf in frames
        }
        for fut in as_completed(futs):
            rows.append(fut.result())

    # Keep timeframe order stable
    order = {tf: i for i, tf in enumerate(frames)}
    rows.sort(key=lambda r: order.get(r.get("interval", ""), 999))

    summary = summarize_mtf(rows)
    # Prefer daily close when available for display
    for preferred in ("1d", "4h", "1h", "1wk", "15m"):
        tf = summary["timeframes"].get(preferred)
        if tf and tf.get("close") is not None:
            summary["close"] = tf["close"]
            break
    return summary


def scan_universe_mtf(
    symbols: list[str],
    timeframes: Iterable[str] = DEFAULT_MTF_FRAMES,
    multiplier: float = 1.0,
    ap: int = 14,
    no_volume: bool = False,
    lookback: int = 3,
    workers: int = 4,
) -> list[dict]:
    """Scan many symbols; each symbol runs its TF jobs internally."""
    results: list[dict] = []
    # Bound outer concurrency so we don't explode yfinance calls
    outer = max(1, min(workers, 4))
    with ThreadPoolExecutor(max_workers=outer) as pool:
        futs = {
            pool.submit(
                analyze_symbol_mtf,
                sym,
                timeframes,
                multiplier,
                ap,
                no_volume,
                lookback,
                max(1, workers // outer or 1),
            ): sym
            for sym in symbols
        }
        for fut in as_completed(futs):
            results.append(fut.result())

    order = {s: i for i, s in enumerate(symbols)}
    results.sort(key=lambda r: order.get(r["symbol"], 9999))
    return results


def portfolio_metrics(summaries: list[dict]) -> dict:
    """Aggregate watchlist-level dashboard numbers."""
    ok = [s for s in summaries if s.get("bias") != "ERROR" and s.get("mtf_score") is not None]
    if not ok:
        return {
            "symbols": len(summaries),
            "scanned": 0,
            "avg_mtf_score": None,
            "bull_count": 0,
            "bear_count": 0,
            "mixed_count": 0,
            "buy_signals": 0,
            "sell_signals": 0,
            "avg_alignment_pct": None,
            "avg_dist_pct": None,
            "breadth": None,
        }

    scores = [s["mtf_score"] for s in ok]
    aligns = [s["alignment_pct"] for s in ok if s.get("alignment_pct") is not None]
    dists = [s["avg_dist_pct"] for s in ok if s.get("avg_dist_pct") is not None]
    bull_c = sum(1 for s in ok if s["bias"] == "BULL")
    bear_c = sum(1 for s in ok if s["bias"] == "BEAR")
    mixed_c = sum(1 for s in ok if s["bias"] == "MIXED")
    buy_sig = sum(s.get("buy_tf", 0) for s in ok)
    sell_sig = sum(s.get("sell_tf", 0) for s in ok)

    return {
        "symbols": len(summaries),
        "scanned": len(ok),
        "avg_mtf_score": round(sum(scores) / len(scores), 1),
        "bull_count": bull_c,
        "bear_count": bear_c,
        "mixed_count": mixed_c,
        "buy_signals": buy_sig,
        "sell_signals": sell_sig,
        "avg_alignment_pct": round(sum(aligns) / len(aligns), 1) if aligns else None,
        "avg_dist_pct": round(sum(dists) / len(dists), 3) if dists else None,
        "breadth": round(100.0 * bull_c / len(ok), 1),
    }


def summaries_to_frame(summaries: list[dict], timeframes: Iterable[str]) -> pd.DataFrame:
    """Flat table for dashboard / CSV (one row per symbol)."""
    frames = list(timeframes)
    rows = []
    for s in summaries:
        row = {
            "symbol": s["symbol"],
            "mtf_score": s.get("mtf_score"),
            "bias": s.get("bias"),
            "alignment_pct": s.get("alignment_pct"),
            "bull_tf": s.get("bull_tf"),
            "bear_tf": s.get("bear_tf"),
            "buy_tf": s.get("buy_tf"),
            "sell_tf": s.get("sell_tf"),
            "avg_dist_pct": s.get("avg_dist_pct"),
            "close": s.get("close"),
        }
        tfs = s.get("timeframes") or {}
        for tf in frames:
            cell = tfs.get(tf) or {}
            trend = "UP" if cell.get("trend_up") else ("DOWN" if cell.get("trend_up") is False else "—")
            sig = cell.get("signal") or "—"
            row[f"{tf}_trend"] = trend
            row[f"{tf}_signal"] = sig
            dist = cell.get("dist_pct")
            row[f"{tf}_dist"] = round(dist, 3) if dist is not None else None
        rows.append(row)
    return pd.DataFrame(rows)
