# AlphaTrend Scanner (NSE F&O)

Validate AlphaTrend BUY/SELL signals across **all NSE F&O equities**, using **closed candles only** on 5m / 15m / 1h.

## 1) Install dependencies (Windows)

Open **Command Prompt** or **PowerShell** inside the project folder  
(`Alpha-Trend-scanner-main`):

```bat
cd "C:\Users\YOUR_USER\My project\Alpha-Trend-scanner-main"

python -m venv .venv
.venv\Scripts\activate

python -m pip install --upgrade pip
pip install -r requirements.txt
```

### What gets installed

| Package | Why |
|---------|-----|
| `pandas` | tables / CSV reports |
| `numpy` | indicator math |
| `yfinance` | NSE price candles (`SYMBOL.NS`) |
| `requests` | live NSE F&O symbol list |
| `streamlit` | web dashboard |
| `plotly` | dashboard charts |

Python **3.10+** recommended.

## 2) How to run

### A) Full NSE F&O scan + **EOD report** (recommended)

```bat
python scanner.py --fno -i 15m -l 3 --signal-only --eod
```

Creates dated folder:

```text
reports\YYYY-MM-DD\
  eod_all_15m.csv
  eod_signals_15m.csv
  eod_summary_15m.txt
```

### B) Multi-timeframe F&O scan + EOD report

```bat
python scanner.py --fno --mtf --mtf-frames 15m,1h,4h,1d -l 3 --eod
```

Writes:

```text
reports\YYYY-MM-DD\
  eod_mtf_all.csv
  eod_mtf_signals.csv
  eod_mtf_summary.txt
```

### C) Dashboard (browser UI)

```bat
streamlit run dashboard.py
```

Then open the local URL Streamlit prints (usually `http://localhost:8501`).  
Choose **NSE F&O (all)** in the sidebar.

### D) Quick smoke test (first 20 names)

```bat
python scanner.py --fno --limit 20 -i 15m -l 3 --eod
```

### E) List F&O universe

```bat
python scanner.py --list-fno --refresh-fno
```

## 3) EOD report — yes, this is included

Use **`--eod`**. Signals are saved automatically under `reports\YYYY-MM-DD\`.

| File | Contents |
|------|----------|
| `eod_signals_*.csv` | Only BUY / SELL rows |
| `eod_all_*.csv` | Full scan (including NONE / BUILDING) |
| `eod_summary_*.txt` | Human-readable day summary |

Optional custom folder:

```bat
python scanner.py --fno -i 15m --eod --reports-dir D:\AT_Reports
```

You can still use `--csv myfile.csv` for a one-off file in addition to `--eod`.

## Closed bars

| Mode | Flag |
|------|------|
| Closed candles only (default) | _(none)_ |
| Live / unconfirmed forming bar | `--include-forming` |

`BUILDING history…` means not enough closed bars yet — wait for candles to finish.

## Tests

```bat
python test_alphatrend.py
python test_mtf.py
python test_closed_bars.py
python test_eod_report.py
```
