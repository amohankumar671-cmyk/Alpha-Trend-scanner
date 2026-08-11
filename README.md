# AlphaTrend Scanner (NSE F&O)

Validate AlphaTrend BUY/SELL signals across **all NSE F&O equities**, using **closed candles only** on 5m / 15m / 1h so signals do not flicker while a bar is still forming.

## Install

```bash
pip install -r requirements.txt
```

## NSE F&O scan (main use)

```bash
# List the F&O universe (cached under nse_fno_symbols.json)
python scanner.py --list-fno --refresh-fno

# Validate signals on all F&O stocks, 15m closed bars
python scanner.py --fno -i 15m -l 3 --signal-only --csv fno_signals.csv

# Multi-timeframe confluence across the F&O book
python scanner.py --fno --mtf --mtf-frames 15m,1h,4h,1d -l 3 --csv fno_mtf.csv

# Smoke test first 20 names
python scanner.py --fno --limit 20 -i 15m -l 3
```

### Closed bars vs forming bars

| Mode | Flag | Behavior |
|------|------|----------|
| **Closed (default)** | _(none)_ | 5m/15m/1h/4h evaluate only fully finished candles — no early flickers |
| **Live / unconfirmed** | `--include-forming` | One-line switch back to the in-progress bar read |

While history is still warming up you may see `BUILDING` instead of an error:

`Building history: need 19 closed bars, have 12 (in-progress bar excluded)`

That is expected near session open / for thin names; counts grow by one when each bar closes.

## Dashboard

```bash
streamlit run dashboard.py
```

Pick **NSE F&O (all)** in the sidebar. Leave “Include forming bar” unchecked for confirmed signals.

## How AlphaTrend works

| Step | Formula |
|------|---------|
| ATR | `SMA(TrueRange, AP)` |
| Trails | `upT = low − ATR×coeff`, `downT = high + ATR×coeff` |
| Gate | `MFI ≥ 50` (or RSI if `--no-volume`) |
| BUY / SELL | Cross of `AT` vs `AT[2]` with alternating filter |

## Files

| File | Role |
|------|------|
| `nse_fno.py` | Live NSE F&O underlying list (+ cache) |
| `datafeed.py` | Yahoo fetch + closed-bar helper |
| `alphatrend.py` | Indicator |
| `mtf.py` | Multi-timeframe scoring |
| `scanner.py` | CLI |
| `dashboard.py` | Streamlit desk |

## Tests

```bash
python test_alphatrend.py
python test_mtf.py
python test_closed_bars.py
```
