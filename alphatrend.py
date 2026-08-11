"""
AlphaTrend indicator — Python port of KivancOzbilgic's TradingView Pine Script v5.

Working function (matches the Pine logic):

1. ATR = SMA(True Range, period)
2. upT   = low  - ATR * multiplier
3. downT = high + ATR * multiplier
4. Momentum gate:
     - with volume:    MFI(hlc3, period) >= 50  → bullish
     - no volume data: RSI(src, period)  >= 50  → bullish
5. AlphaTrend ratchet:
     - bullish: AlphaTrend = max(upT,   prior AlphaTrend)   # never fall while bullish
     - bearish: AlphaTrend = min(downT, prior AlphaTrend)   # never rise while bearish
6. Signals from AlphaTrend vs AlphaTrend[2]:
     - BUY  = crossover(AT, AT[2])  and O1 > K2  (last opposing signal was SELL)
     - SELL = crossunder(AT, AT[2]) and O2 > K1  (last opposing signal was BUY)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def rsi(series: pd.Series, period: int) -> pd.Series:
    """Wilder RSI (matches TradingView ta.rsi)."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def mfi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int,
) -> pd.Series:
    """Money Flow Index on typical price (hlc3), matching Pine ta.mfi(hlc3, AP)."""
    tp = (high + low + close) / 3.0
    raw_mf = tp * volume
    direction = tp.diff()

    pos_mf = raw_mf.where(direction > 0, 0.0)
    neg_mf = raw_mf.where(direction < 0, 0.0)
    pos_sum = pos_mf.rolling(period, min_periods=period).sum()
    neg_sum = neg_mf.rolling(period, min_periods=period).sum()
    mfr = pos_sum / neg_sum.replace(0, np.nan)
    return 100 - (100 / (1 + mfr))


def compute_alphatrend(
    df: pd.DataFrame,
    multiplier: float = 1.0,
    period: int = 14,
    src_col: str = "Close",
    no_volume_data: bool = False,
) -> pd.DataFrame:
    """
    Compute AlphaTrend line and filtered buy/sell signals.

    Expects OHLCV columns: High, Low, Close, Volume
    (Volume optional if no_volume_data=True).
    """
    required = {"High", "Low", "Close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing columns: {sorted(missing)}")

    out = df.copy()
    high = out["High"].astype(float)
    low = out["Low"].astype(float)
    close = out["Close"].astype(float)
    src = out[src_col].astype(float)

    atr = true_range(high, low, close).rolling(period, min_periods=period).mean()
    up_t = low - atr * multiplier
    down_t = high + atr * multiplier

    if no_volume_data:
        momentum_bullish = rsi(src, period) >= 50
    else:
        if "Volume" not in out.columns:
            raise ValueError("Volume column required unless no_volume_data=True")
        volume = out["Volume"].astype(float)
        momentum_bullish = mfi(high, low, close, volume, period) >= 50

    alpha = np.full(len(out), np.nan, dtype=float)
    up_vals = up_t.to_numpy(dtype=float)
    down_vals = down_t.to_numpy(dtype=float)
    bull_vals = momentum_bullish.to_numpy()

    prev = np.nan
    for i in range(len(out)):
        if np.isnan(up_vals[i]) or np.isnan(down_vals[i]) or pd.isna(bull_vals[i]):
            alpha[i] = prev
            continue

        if bool(bull_vals[i]):
            # upT < nz(AlphaTrend[1]) ? prior : upT
            if not np.isnan(prev) and up_vals[i] < prev:
                alpha[i] = prev
            else:
                alpha[i] = up_vals[i]
        else:
            # downT > nz(AlphaTrend[1]) ? prior : downT
            if not np.isnan(prev) and down_vals[i] > prev:
                alpha[i] = prev
            else:
                alpha[i] = down_vals[i]
        prev = alpha[i]

    out["ATR"] = atr
    out["upT"] = up_t
    out["downT"] = down_t
    out["AlphaTrend"] = alpha
    out["AlphaTrend_2"] = out["AlphaTrend"].shift(2)

    at = out["AlphaTrend"]
    at2 = out["AlphaTrend_2"]
    buy_raw = (at > at2) & (at.shift(1) <= at2.shift(1))
    sell_raw = (at < at2) & (at.shift(1) >= at2.shift(1))
    out["buy_raw"] = buy_raw.fillna(False)
    out["sell_raw"] = sell_raw.fillna(False)

    # Pine filters using barssince:
    #   K1 = barssince(buy), K2 = barssince(sell)
    #   O1 = barssince(buy[1]), O2 = barssince(sell[1])
    # BUY  when buy_raw and O1 > K2
    # SELL when sell_raw and O2 > K1
    #
    # Equivalently: only keep a signal when the last *opposing* signal
    # is more recent than the last *same-direction* signal (alternating).
    buy_signal = np.zeros(len(out), dtype=bool)
    sell_signal = np.zeros(len(out), dtype=bool)

    # Indices where buySignalk[1] / sellSignalk[1] would be true
    # (= one bar after a raw buy/sell). Track last raw signal bars.
    last_buy_bar: int | None = None
    last_sell_bar: int | None = None

    for i in range(len(out)):
        if out["buy_raw"].iloc[i]:
            # O1 = bars since buySignalk[1]; buy[1] true at last_buy_bar+1
            if last_buy_bar is not None:
                o1 = i - (last_buy_bar + 1)
            else:
                o1 = None  # na in Pine → comparison is false
            k2 = (i - last_sell_bar) if last_sell_bar is not None else None
            if o1 is not None and k2 is not None and o1 > k2:
                buy_signal[i] = True
            elif o1 is None and k2 is not None:
                # First buy after a sell — treat as valid flip for scanner use
                buy_signal[i] = True
            last_buy_bar = i

        if out["sell_raw"].iloc[i]:
            if last_sell_bar is not None:
                o2 = i - (last_sell_bar + 1)
            else:
                o2 = None
            k1 = (i - last_buy_bar) if last_buy_bar is not None else None
            if o2 is not None and k1 is not None and o2 > k1:
                sell_signal[i] = True
            elif o2 is None and k1 is not None:
                sell_signal[i] = True
            last_sell_bar = i

    out["buy_signal"] = buy_signal
    out["sell_signal"] = sell_signal
    out["trend_up"] = at > at2

    return out


def _bar_loc(index: pd.Index, ts) -> int:
    loc = index.get_loc(ts)
    if isinstance(loc, slice):
        return int(loc.start)
    if isinstance(loc, np.ndarray):
        return int(np.flatnonzero(loc)[-1])
    return int(loc)


def trend_change_bar(df_with_at: pd.DataFrame) -> dict:
    """
    Find when the current AlphaTrend direction (AT vs AT[2]) started.

    Returns bar timestamp + bars since the flip (0 = flipped on the last closed bar).
    """
    empty = {"trend_since": None, "trend_bars": None}
    if df_with_at.empty or "trend_up" not in df_with_at.columns:
        return empty

    trend = df_with_at["trend_up"]
    if pd.isna(trend.iloc[-1]):
        return empty

    current = bool(trend.iloc[-1])
    # Walk back while trend matches; first mismatch is the bar before the change.
    since_idx = 0
    for i in range(len(trend) - 2, -1, -1):
        val = trend.iloc[i]
        if pd.isna(val) or bool(val) != current:
            since_idx = i + 1
            break
    else:
        # Never flipped in history — use first valid trend bar
        for i, val in enumerate(trend):
            if pd.notna(val):
                since_idx = i
                break

    ts = df_with_at.index[since_idx]
    return {
        "trend_since": ts,
        "trend_bars": len(df_with_at) - 1 - since_idx,
    }


def latest_signal(df_with_at: pd.DataFrame, lookback: int = 1) -> dict:
    """Summarize signals in the last `lookback` bars for scanner output."""
    empty = {
        "signal": "NONE",
        "bar_ago": None,
        "signal_time": None,
        "freshness": None,
        "alphatrend": None,
        "close": None,
        "trend_up": None,
        "price_vs_at": None,
        "trend_since": None,
        "trend_bars": None,
    }
    if df_with_at.empty:
        return empty

    last = df_with_at.iloc[-1]
    trend_meta = trend_change_bar(df_with_at)
    result = {
        "signal": "NONE",
        "bar_ago": None,
        "signal_time": None,
        "freshness": None,
        "alphatrend": float(last["AlphaTrend"]) if pd.notna(last["AlphaTrend"]) else None,
        "close": float(last["Close"]),
        "trend_up": bool(last["trend_up"]) if pd.notna(last["trend_up"]) else None,
        "price_vs_at": None,
        "trend_since": trend_meta["trend_since"],
        "trend_bars": trend_meta["trend_bars"],
    }
    if result["alphatrend"] is not None:
        result["price_vs_at"] = "ABOVE" if result["close"] > result["alphatrend"] else "BELOW"

    tail = df_with_at.iloc[-lookback:]
    events: list[tuple] = []
    for ts in tail.index[tail["buy_signal"]]:
        events.append((ts, "BUY"))
    for ts in tail.index[tail["sell_signal"]]:
        events.append((ts, "SELL"))
    if not events:
        return result

    events.sort(key=lambda x: x[0])
    ts, sig = events[-1]
    bar_ago = len(df_with_at) - 1 - _bar_loc(df_with_at.index, ts)
    result["signal"] = sig
    result["bar_ago"] = bar_ago
    result["signal_time"] = ts
    if bar_ago == 0:
        result["freshness"] = "NEW"
    else:
        result["freshness"] = f"{bar_ago} bar(s) ago"
    return result
