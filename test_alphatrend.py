"""Unit tests for AlphaTrend core logic (no network)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphatrend import compute_alphatrend, latest_signal, mfi, rsi, true_range


def _synthetic_ohlcv(n: int = 80, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.2, 1.5, n)
    low = close - rng.uniform(0.2, 1.5, n)
    open_ = close + rng.normal(0, 0.3, n)
    volume = rng.integers(100_000, 500_000, n).astype(float)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


def test_true_range_non_negative():
    df = _synthetic_ohlcv()
    tr = true_range(df["High"], df["Low"], df["Close"])
    assert (tr.dropna() >= 0).all()


def test_rsi_bounds():
    df = _synthetic_ohlcv()
    values = rsi(df["Close"], 14).dropna()
    assert values.min() >= 0
    assert values.max() <= 100


def test_mfi_bounds():
    df = _synthetic_ohlcv()
    values = mfi(df["High"], df["Low"], df["Close"], df["Volume"], 14).dropna()
    assert values.min() >= 0
    assert values.max() <= 100


def test_alphatrend_columns_and_ratchet():
    df = _synthetic_ohlcv()
    out = compute_alphatrend(df, multiplier=1.0, period=14)
    for col in ("AlphaTrend", "buy_raw", "sell_raw", "buy_signal", "sell_signal", "trend_up"):
        assert col in out.columns
    # After warm-up, AlphaTrend should be finite
    assert out["AlphaTrend"].iloc[20:].notna().all()


def test_no_volume_mode():
    df = _synthetic_ohlcv()
    out = compute_alphatrend(df.drop(columns=["Volume"]), no_volume_data=True)
    assert out["AlphaTrend"].iloc[30:].notna().any()


def test_signals_are_boolean():
    df = _synthetic_ohlcv(n=120)
    out = compute_alphatrend(df)
    assert out["buy_signal"].dtype == bool
    assert out["sell_signal"].dtype == bool
    # Filtered signals are a subset of raw crosses
    assert (out["buy_signal"] <= out["buy_raw"]).all()
    assert (out["sell_signal"] <= out["sell_raw"]).all()


def test_latest_signal_shape():
    df = _synthetic_ohlcv(n=120)
    out = compute_alphatrend(df)
    info = latest_signal(out, lookback=5)
    assert "signal" in info
    assert info["signal"] in ("BUY", "SELL", "NONE")
    assert info["close"] is not None


if __name__ == "__main__":
    test_true_range_non_negative()
    test_rsi_bounds()
    test_mfi_bounds()
    test_alphatrend_columns_and_ratchet()
    test_no_volume_mode()
    test_signals_are_boolean()
    test_latest_signal_shape()
    print("All tests passed.")
