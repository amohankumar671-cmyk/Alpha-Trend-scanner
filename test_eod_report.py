"""Offline tests for EOD report writers."""

from __future__ import annotations

from pathlib import Path

from eod_report import save_mtf_eod, save_single_tf_eod


def test_single_tf_eod(tmp_path: Path | None = None):
    base = tmp_path or Path("reports_test_tmp")
    results = [
        {
            "symbol": "AAA.NS",
            "signal": "BUY",
            "close": 100.0,
            "alphatrend": 99.0,
            "trend_up": True,
            "bar_ago": 0,
        },
        {
            "symbol": "BBB.NS",
            "signal": "NONE",
            "close": 50.0,
            "alphatrend": 51.0,
            "trend_up": False,
            "bar_ago": None,
        },
    ]
    paths = save_single_tf_eod(results, interval="15m", lookback=3, base_dir=base)
    assert paths["signals"].exists()
    assert paths["summary"].exists()
    text = paths["summary"].read_text(encoding="utf-8")
    assert "BUY" in text
    assert "AAA.NS" in text


def test_mtf_eod(tmp_path: Path | None = None):
    base = tmp_path or Path("reports_test_tmp")
    summaries = [
        {
            "symbol": "CCC.NS",
            "mtf_score": 40.0,
            "bias": "BULL",
            "alignment_pct": 80.0,
            "bull_tf": 4,
            "bear_tf": 1,
            "buy_tf": 1,
            "sell_tf": 0,
            "avg_dist_pct": 1.2,
            "close": 123.0,
            "timeframes": {
                "15m": {"signal": "BUY", "trend_up": True},
                "1h": {"signal": "NONE", "trend_up": True},
            },
        }
    ]
    paths = save_mtf_eod(summaries, ["15m", "1h"], lookback=3, base_dir=base)
    assert paths["all"].exists()
    assert paths["signals"].exists()
    assert "CCC.NS" in paths["summary"].read_text(encoding="utf-8")


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as td:
        root = Path(td)
        test_single_tf_eod(root)
        test_mtf_eod(root)
    print("EOD report tests passed.")
