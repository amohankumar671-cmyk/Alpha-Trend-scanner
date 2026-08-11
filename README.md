# AlphaTrend Scanner (NSE F&O)

Validate AlphaTrend BUY/SELL signals across **all NSE F&O equities**, using **closed candles only** on 5m / 15m / 1h.

## Important (Windows)

1. Open the **Alpha-Trend-scanner** folder (the one that contains `scanner.py` and `dashboard.py`).
2. Do **not** run these commands from `CVC-trading-method` — that is a different project.
3. Use **Python 3.12** (recommended). Python 3.14 on some Windows PCs is broken (`_ctypes` DLL error).

---

## 1) Fix Python first (if you see `_ctypes` / `ensurepip` errors)

Your log shows:

`ImportError: DLL load failed while importing _ctypes`

That means the Python install itself is damaged. Fix it before installing packages:

1. Uninstall **Python 3.14** from Windows Settings → Apps.
2. Download **Python 3.12.x** from https://www.python.org/downloads/windows/
3. Run installer and tick:
   - **Add python.exe to PATH**
   - **Install for all users** (optional)
4. Open a **new** Command Prompt and check:

```bat
py -3.12 --version
py -3.12 -c "import ctypes; print('ctypes OK')"
```

If that prints `ctypes OK`, continue.

---

## 2) Go to the correct folder

Find where you extracted/cloned the scanner. Examples:

```bat
cd /d "%USERPROFILE%\Downloads\Alpha-Trend-scanner-main"
```

or (if under Documents / My project):

```bat
cd /d "%USERPROFILE%\Documents\My project\Alpha-Trend-scanner-main"
```

Confirm you see `scanner.py`:

```bat
dir scanner.py
```

If `File Not Found`, you are still in the wrong folder.

---

## 3) Install dependencies

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Packages installed

| Package | Why |
|---------|-----|
| `pandas` | tables / CSV / EOD reports |
| `numpy` | indicator math |
| `yfinance` | NSE candles (`SYMBOL.NS`) |
| `requests` | NSE F&O symbol list |
| `streamlit` | dashboard |
| `plotly` | charts |

---

## 4) Run

### F&O scan + EOD report

```bat
python scanner.py --fno -i 15m -l 3 --signal-only --eod
```

Creates:

```text
reports\YYYY-MM-DD\
  eod_signals_15m.csv
  eod_all_15m.csv
  eod_summary_15m.txt
```

### Multi-timeframe + EOD

```bat
python scanner.py --fno --mtf --mtf-frames 5m,15m,1h,4h,1d,1wk -l 3 --eod
```

### Dashboard

```bat
streamlit run dashboard.py
```

Open the URL shown (usually `http://localhost:8501`).

**Dashboard tips**
- Default frames include **5m** for short-term trend.
- Each timeframe shows **signal_time (IST)** and **freshness** (`NEW` vs `N bar(s) ago`).
- **trend_since** = when the current UP/DOWN direction started on that frame.
- Use **Copy stock names** (text boxes) to Ctrl+A / Ctrl+C bare tickers for your broker.

### Smoke test

```bat
python scanner.py --fno --limit 20 -i 15m -l 3 --eod
```

---

## What went wrong in your log

| Error | Cause |
|-------|--------|
| `The system cannot find the path specified` | `YOUR_USER` was a placeholder, not a real path |
| Commands ran in `C:\Users\mktj1\CVC-trading-method` | Wrong project folder |
| `ensurepip` / `.venv` failed | Broken Python 3.14 |
| `_ctypes` DLL errors from pip | Same broken Python install |
| `pip` tried to install `flask`, `nse`, `schedule` | That is **CVC-trading-method** `requirements.txt`, not this scanner |

---

## EOD report

Yes — use `--eod`. Signals are saved under `reports\YYYY-MM-DD\`.

---

## Tests

```bat
python test_alphatrend.py
python test_mtf.py
python test_closed_bars.py
python test_eod_report.py
```
