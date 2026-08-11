"""
NSE F&O universe helpers.

Fetches the official equity derivatives underlying list from NSE and
maps symbols to Yahoo Finance tickers (SYMBOL.NS).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

NSE_UNDERLYING_URL = "https://www.nseindia.com/api/underlying-information"
NSE_HOME = "https://www.nseindia.com"
CACHE_PATH = Path(__file__).resolve().parent / "nse_fno_symbols.json"

# Index underlyings are not equity cash symbols on Yahoo the same way;
# keep them optional / separate from the stock F&O scan.
INDEX_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "NIFTYFPI",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/products-services/equity-derivatives-list-underlyings-information",
        }
    )
    return s


def fetch_fno_equity_symbols(include_indices: bool = False, retries: int = 3) -> list[dict]:
    """
    Return list of dicts: {symbol, underlying, yf_symbol}.

    Equity symbols are mapped to Yahoo as SYMBOL.NS.
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            s = _session()
            s.get(NSE_HOME, timeout=25)
            r = s.get(NSE_UNDERLYING_URL, timeout=25)
            r.raise_for_status()
            payload = r.json().get("data") or {}
            rows: list[dict] = []

            if include_indices:
                for item in payload.get("IndexList") or []:
                    sym = str(item.get("symbol") or "").upper().strip()
                    if not sym:
                        continue
                    rows.append(
                        {
                            "symbol": sym,
                            "underlying": item.get("underlying") or sym,
                            "yf_symbol": _index_yahoo(sym),
                            "kind": "index",
                        }
                    )

            for item in payload.get("UnderlyingList") or []:
                sym = str(item.get("symbol") or "").upper().strip()
                if not sym or (sym in INDEX_SYMBOLS and not include_indices):
                    continue
                rows.append(
                    {
                        "symbol": sym,
                        "underlying": item.get("underlying") or sym,
                        "yf_symbol": f"{sym}.NS",
                        "kind": "equity",
                    }
                )

            if not rows:
                raise RuntimeError("NSE underlying list returned empty")
            return rows
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"Failed to fetch NSE F&O list: {last_err}")


def _index_yahoo(sym: str) -> str:
    # Common Yahoo mappings for NSE index underlyings
    mapping = {
        "NIFTY": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
        "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
        "NIFTYNXT50": "^NSMIDCP",
    }
    return mapping.get(sym, f"{sym}.NS")


def save_fno_cache(rows: list[dict], path: Path | None = None) -> Path:
    path = path or CACHE_PATH
    payload = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(rows),
        "symbols": rows,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_fno_cache(path: Path | None = None) -> list[dict]:
    path = path or CACHE_PATH
    if not path.exists():
        raise FileNotFoundError(f"No F&O cache at {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("symbols") or [])


def get_fno_symbols(
    refresh: bool = False,
    include_indices: bool = False,
    cache_path: Path | None = None,
) -> list[dict]:
    """
    Prefer live NSE list; fall back to on-disk cache if the network call fails.
    """
    cache_path = cache_path or CACHE_PATH
    if not refresh and cache_path.exists():
        try:
            cached = load_fno_cache(cache_path)
            if cached and (include_indices or all(r.get("kind") != "index" for r in cached)):
                if not include_indices:
                    cached = [r for r in cached if r.get("kind") != "index"]
                if cached:
                    return cached
        except Exception:  # noqa: BLE001
            pass

    try:
        rows = fetch_fno_equity_symbols(include_indices=include_indices)
        save_fno_cache(rows, cache_path)
        return rows
    except Exception:
        if cache_path.exists():
            cached = load_fno_cache(cache_path)
            if not include_indices:
                cached = [r for r in cached if r.get("kind") != "index"]
            if cached:
                return cached
        raise


def fno_yahoo_tickers(
    refresh: bool = False,
    include_indices: bool = False,
) -> list[str]:
    rows = get_fno_symbols(refresh=refresh, include_indices=include_indices)
    return [r["yf_symbol"] for r in rows if r.get("yf_symbol")]


if __name__ == "__main__":
    rows = get_fno_symbols(refresh=True)
    print(f"F&O equities: {len(rows)}")
    print(", ".join(r["symbol"] for r in rows[:15]), "...")
