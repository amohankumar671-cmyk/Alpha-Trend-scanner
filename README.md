# AlphaTrend Scanner

Python port of KivancOzbilgic's AlphaTrend Pine Script v5, with:

- single-timeframe scanner
- **multi-timeframe (MTF) confluence analysis**
- **Streamlit dashboard** with desk metric numbers

## How AlphaTrend works

| Step | Formula |
|------|---------|
| ATR | `SMA(TrueRange, AP)` with default `AP=14` |
| Support trail | `upT = low − ATR × coeff` |
| Resistance trail | `downT = high + ATR × coeff` |
| Momentum gate | `MFI(hlc3, AP) ≥ 50` (or `RSI(close, AP) ≥ 50` if no volume) |
| Line | Bullish → ratchet with `upT`. Bearish → ratchet with `downT`. |
| BUY / SELL | Cross of `AlphaTrend` vs `AlphaTrend[2]`, alternating filter |

## Install

```bash
pip install -r requirements.txt
```

## Dashboard (MTF + numbers)

```bash
streamlit run dashboard.py
```

The desk shows:

| Number | Meaning |
|--------|---------|
| **MTF Score** | Weighted confluence −100…+100 across selected timeframes |
| **Breadth** | % of watchlist symbols with bullish bias |
| **Alignment** | Avg % of timeframes trending up per symbol |
| **BUY TFs / SELL TFs** | Active signal counts across all frames |
| **Dist vs AT** | Avg % distance of price to AlphaTrend |

Also includes a timeframe heatmap, score bars, per-symbol detail chart, and CSV download.

## CLI scan

```bash
# Single timeframe
python scanner.py -f symbols.txt -i 1d -l 3

# Multi-timeframe confluence
python scanner.py --mtf -f symbols.txt -l 3

# Only strong MTF setups
python scanner.py --mtf -s AAPL,MSFT,NVDA --mtf-min-score 40

# Custom frames + CSV
python scanner.py --mtf --mtf-frames 1h,4h,1d,1wk --csv mtf.csv
```

### CLI options

| Flag | Meaning |
|------|---------|
| `-m / --multiplier` | Trail width (`coeff`) |
| `--ap` | Common period (`AP`) |
| `--no-volume` | RSI gate instead of MFI |
| `-i` | Single-TF interval |
| `--mtf` | Enable multi-timeframe mode |
| `--mtf-frames` | Frames list (default `15m,1h,4h,1d,1wk`) |
| `--mtf-min-score` | Filter by absolute MTF score |
| `-l` | Signal lookback bars |

## Library use

```python
from mtf import analyze_symbol_mtf, scan_universe_mtf, portfolio_metrics

summary = analyze_symbol_mtf("AAPL", timeframes=["1h", "4h", "1d", "1wk"])
print(summary["mtf_score"], summary["bias"], summary["alignment_pct"])

rows = scan_universe_mtf(["AAPL", "MSFT", "NVDA"])
print(portfolio_metrics(rows))
```

## Tests

```bash
python test_alphatrend.py
python test_mtf.py
```

## Files

- `alphatrend.py` — indicator
- `datafeed.py` — yfinance helpers
- `mtf.py` — multi-timeframe scoring
- `scanner.py` — CLI (single + MTF)
- `dashboard.py` — Streamlit desk
- `symbols.txt` — sample watchlist
