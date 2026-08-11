"""Unit tests for multi-timeframe scoring (no network)."""

from __future__ import annotations

from mtf import portfolio_metrics, summarize_mtf, summaries_to_frame


def _tf(symbol: str, interval: str, trend_up: bool, signal: str = "NONE", dist: float = 1.0) -> dict:
    return {
        "symbol": symbol,
        "interval": interval,
        "signal": signal,
        "trend_up": trend_up,
        "price_vs_at": "ABOVE" if trend_up else "BELOW",
        "dist_pct": dist if trend_up else -dist,
        "close": 100.0,
        "alphatrend": 99.0,
    }


def test_summarize_mtf_bullish():
    rows = [
        _tf("AAA", "15m", True, "BUY"),
        _tf("AAA", "1h", True),
        _tf("AAA", "4h", True),
        _tf("AAA", "1d", True, "BUY"),
        _tf("AAA", "1wk", True),
    ]
    s = summarize_mtf(rows)
    assert s["bias"] == "BULL"
    assert s["mtf_score"] is not None and s["mtf_score"] > 25
    assert s["bull_tf"] == 5
    assert s["bear_tf"] == 0
    assert s["buy_tf"] == 2
    assert s["alignment_pct"] == 100.0


def test_summarize_mtf_bearish():
    rows = [
        _tf("BBB", "15m", False, "SELL"),
        _tf("BBB", "1h", False),
        _tf("BBB", "4h", False, "SELL"),
        _tf("BBB", "1d", False),
        _tf("BBB", "1wk", False),
    ]
    s = summarize_mtf(rows)
    assert s["bias"] == "BEAR"
    assert s["mtf_score"] < -25
    assert s["sell_tf"] == 2


def test_portfolio_metrics():
    bull = summarize_mtf([_tf("A", tf, True) for tf in ("1h", "4h", "1d")])
    bear = summarize_mtf([_tf("B", tf, False) for tf in ("1h", "4h", "1d")])
    pm = portfolio_metrics([bull, bear])
    assert pm["scanned"] == 2
    assert pm["bull_count"] == 1
    assert pm["bear_count"] == 1
    assert pm["breadth"] == 50.0
    assert pm["avg_mtf_score"] is not None


def test_summaries_to_frame():
    s = summarize_mtf([_tf("CCC", "1d", True, "BUY"), _tf("CCC", "1h", False)])
    df = summaries_to_frame([s], ["1h", "1d"])
    assert list(df["symbol"]) == ["CCC"]
    assert list(df["ticker"]) == ["CCC"]
    assert "1d_trend" in df.columns
    assert "1d_signal_time" in df.columns
    assert "1d_trend_since" in df.columns
    assert "mtf_score" in df.columns


def test_bare_ticker_and_format_ist():
    from datafeed import bare_ticker, format_ist
    import pandas as pd

    assert bare_ticker("RELIANCE.NS") == "RELIANCE"
    assert bare_ticker("TCS") == "TCS"
    ts = pd.Timestamp("2026-08-11 10:15:00", tz="Asia/Kolkata")
    assert format_ist(ts) == "2026-08-11 10:15 IST"
    assert format_ist(None) is None


if __name__ == "__main__":
    test_summarize_mtf_bullish()
    test_summarize_mtf_bearish()
    test_portfolio_metrics()
    test_summaries_to_frame()
    test_bare_ticker_and_format_ist()
    print("MTF tests passed.")
