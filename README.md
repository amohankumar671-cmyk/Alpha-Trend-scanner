# AlphaTrend Scanner

Python port of [KivancOzbilgic's AlphaTrend](https://www.tradingview.com) Pine Script v5, plus a multi-symbol scanner.

## How AlphaTrend works

| Step | Formula |
|------|---------|
| ATR | `SMA(TrueRange, AP)` with default `AP=14` |
| Support trail | `upT = low − ATR × coeff` |
| Resistance trail | `downT = high + ATR × coeff` |
| Momentum gate | `MFI(hlc3, AP) ≥ 50` (or `RSI(close, AP) ≥ 50` if no volume) |
| Line | Bullish → ratchet with `upT` (never falls). Bearish → ratchet with `downT` (never rises). |
| BUY | `crossover(AlphaTrend, AlphaTrend[2])` and last opposing signal was SELL |
| SELL | `crossunder(AlphaTrend, AlphaTrend[2])` and last opposing signal was BUY |

The plot fill turns green when `AlphaTrend > AlphaTrend[2]`, red otherwise.

## Install

```bash
pip install -r requirements.txt
```

## Scan

```bash
# Default watchlist, daily bars, last-bar signals
python scanner.py

# Custom symbols / timeframe / Pine inputs
python scanner.py -s AAPL,MSFT,NVDA -i 1d -m 1.0 --ap 14

# From file, only print active signals, wider lookback
python scanner.py -f symbols.txt --signal-only -l 3

# No-volume mode (RSI gate, Pine novolumedata=true)
python scanner.py -s BTC-USD,ETH-USD --no-volume -i 1d

# Export CSV
python scanner.py -f symbols.txt --csv results.csv
```

### CLI options

| Flag | Meaning | Pine equivalent |
|------|---------|-----------------|
| `-m / --multiplier` | Trail width | `coeff` |
| `--ap` | Common period | `AP` |
| `--no-volume` | Use RSI instead of MFI | `novolumedata` |
| `-i` | Bar interval | chart timeframe |
| `-l` | Bars to search for a signal | confirmed vs live |

## Library use

```python
import yfinance as yf
from alphatrend import compute_alphatrend, latest_signal

df = yf.download("AAPL", period="6mo", interval="1d", auto_adjust=True, progress=False)
if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
    df.columns = [c[0] for c in df.columns]

out = compute_alphatrend(df, multiplier=1.0, period=14)
print(latest_signal(out, lookback=1))
print(out[["Close", "AlphaTrend", "buy_signal", "sell_signal"]].tail())
```

## Tests

```bash
python test_alphatrend.py
```

## Files

- `alphatrend.py` — indicator calculation
- `scanner.py` — CLI multi-symbol scanner (yfinance)
- `symbols.txt` — sample watchlist
- `test_alphatrend.py` — offline unit tests
