#!/usr/bin/env python3
"""
AlphaTrend multi-timeframe dashboard.

Launch:
  streamlit run dashboard.py
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from datafeed import DEFAULT_MTF_FRAMES, DEFAULT_SYMBOLS, bare_ticker, parse_symbols
from mtf import (
    analyze_symbol_mtf,
    portfolio_metrics,
    scan_universe_mtf,
    summaries_to_frame,
)
from nse_fno import fno_yahoo_tickers
from eod_report import save_mtf_eod

st.set_page_config(
    page_title="AlphaTrend MTF Desk",
    page_icon="AT",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Atmosphere: cool slate + sea-glass (avoid purple / cream-terracotta / glow clichés)
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Instrument+Serif:ital@0;1&display=swap');

:root {
  --ink: #12202c;
  --muted: #5a6b78;
  --line: #d5dde4;
  --panel: rgba(255,255,255,0.72);
  --bull: #0f7a5a;
  --bear: #b42318;
  --mix: #9a6700;
  --accent: #1f6f8b;
}

.stApp {
  background:
    radial-gradient(1200px 500px at 10% -10%, #cfe8ef 0%, transparent 55%),
    radial-gradient(900px 420px at 100% 0%, #e8f0e6 0%, transparent 50%),
    linear-gradient(180deg, #eef3f6 0%, #e4ebf0 100%);
  color: var(--ink);
  font-family: 'DM Sans', sans-serif;
}

h1, h2, h3, .brand {
  font-family: 'Instrument Serif', Georgia, serif !important;
  letter-spacing: -0.02em;
}

.brand-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  margin-bottom: 0.75rem;
}
.brand {
  font-size: 2.6rem;
  line-height: 1;
  color: var(--ink);
  margin: 0;
}
.brand-sub {
  color: var(--muted);
  font-size: 0.98rem;
  max-width: 42rem;
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 0.75rem;
  margin: 1rem 0 1.25rem;
}
@media (max-width: 1100px) {
  .metric-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.metric-cell {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 0.85rem 1rem;
  backdrop-filter: blur(8px);
}
.metric-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  margin-bottom: 0.25rem;
}
.metric-value {
  font-size: 1.75rem;
  font-weight: 700;
  line-height: 1.1;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.metric-hint {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0.2rem;
}
.metric-value.bull { color: var(--bull); }
.metric-value.bear { color: var(--bear); }
.metric-value.mix { color: var(--mix); }

.copy-box {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0.75rem 1rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92rem;
  user-select: all;
  -webkit-user-select: all;
  cursor: text;
  color: var(--ink);
  line-height: 1.45;
  word-break: break-all;
}

div[data-testid="stSidebar"] {
  background: #f7fafb;
  border-right: 1px solid var(--line);
}
</style>
""",
    unsafe_allow_html=True,
)


def _fmt(n, digits=1, suffix=""):
    if n is None:
        return "—"
    return f"{n:.{digits}f}{suffix}"


def metric_strip(pm: dict) -> None:
    avg = pm.get("avg_mtf_score")
    cls = "mix"
    if avg is not None and avg >= 25:
        cls = "bull"
    elif avg is not None and avg <= -25:
        cls = "bear"

    cells = [
        ("MTF Score", _fmt(avg, 1), "watchlist average −100..+100", cls),
        ("Breadth", _fmt(pm.get("breadth"), 1, "%"), f"{pm.get('bull_count', 0)} bull / {pm.get('bear_count', 0)} bear", "bull" if (pm.get("breadth") or 0) >= 55 else ("bear" if (pm.get("breadth") or 0) <= 45 else "mix")),
        ("Alignment", _fmt(pm.get("avg_alignment_pct"), 1, "%"), "avg % of TFs trending up", ""),
        ("BUY TFs", str(pm.get("buy_signals", 0)), "active buy signals across frames", "bull"),
        ("SELL TFs", str(pm.get("sell_signals", 0)), "active sell signals across frames", "bear"),
        ("Dist vs AT", _fmt(pm.get("avg_dist_pct"), 2, "%"), "avg price distance to AlphaTrend", ""),
    ]
    parts = ['<div class="metric-strip">']
    for label, value, hint, klass in cells:
        parts.append(
            f'<div class="metric-cell"><div class="metric-label">{html.escape(label)}</div>'
            f'<div class="metric-value {klass}">{html.escape(value)}</div>'
            f'<div class="metric-hint">{html.escape(hint)}</div></div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def build_heatmap(summaries: list[dict], timeframes: list[str]) -> go.Figure:
    symbols = [s["symbol"] for s in summaries]
    z = []
    text = []
    hover = []
    for s in summaries:
        row_z = []
        row_t = []
        row_h = []
        tfs = s.get("timeframes") or {}
        for tf in timeframes:
            cell = tfs.get(tf) or {}
            trend_lbl = (
                "UP"
                if cell.get("trend_up")
                else ("DOWN" if cell.get("trend_up") is False else "n/a")
            )
            sig_time = cell.get("signal_time_ist") or "—"
            trend_since = cell.get("trend_since_ist") or "—"
            fresh = cell.get("freshness") or "—"
            if cell.get("signal") == "ERROR" or cell.get("trend_up") is None:
                row_z.append(0)
                row_t.append("n/a")
                row_h.append(f"{s['symbol']} · {tf}<br>n/a")
            elif cell.get("signal") == "BUY":
                row_z.append(2)
                row_t.append("BUY / UP" if cell.get("trend_up") else "BUY")
                row_h.append(
                    f"{s['symbol']} · {tf}<br>BUY · trend {trend_lbl}"
                    f"<br>signal @ {sig_time} ({fresh})"
                    f"<br>trend since {trend_since}"
                )
            elif cell.get("signal") == "SELL":
                row_z.append(-2)
                row_t.append("SELL / DOWN" if not cell.get("trend_up") else "SELL")
                row_h.append(
                    f"{s['symbol']} · {tf}<br>SELL · trend {trend_lbl}"
                    f"<br>signal @ {sig_time} ({fresh})"
                    f"<br>trend since {trend_since}"
                )
            else:
                row_z.append(1 if cell.get("trend_up") else -1)
                row_t.append("UP" if cell.get("trend_up") else "DOWN")
                row_h.append(
                    f"{s['symbol']} · {tf}<br>trend {trend_lbl}"
                    f"<br>no BUY/SELL in lookback"
                    f"<br>trend since {trend_since}"
                )
        z.append(row_z)
        text.append(row_t)
        hover.append(row_h)

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=timeframes,
            y=symbols,
            text=text,
            texttemplate="%{text}",
            customdata=hover,
            colorscale=[
                [0.0, "#b42318"],
                [0.25, "#f0b4ae"],
                [0.5, "#eef3f6"],
                [0.75, "#9fd5c0"],
                [1.0, "#0f7a5a"],
            ],
            zmid=0,
            showscale=False,
            hovertemplate="%{customdata}<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=max(280, 28 * len(symbols) + 80),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans", color="#12202c"),
        xaxis=dict(side="top"),
    )
    return fig


def build_score_bar(df: pd.DataFrame) -> go.Figure:
    plot_df = df.sort_values("mtf_score", ascending=True)
    colors = [
        "#0f7a5a" if v >= 25 else ("#b42318" if v <= -25 else "#9a6700")
        for v in plot_df["mtf_score"].fillna(0)
    ]
    fig = go.Figure(
        go.Bar(
            x=plot_df["mtf_score"],
            y=plot_df["symbol"],
            orientation="h",
            marker_color=colors,
            text=[f"{v:.1f}" if pd.notna(v) else "—" for v in plot_df["mtf_score"]],
            textposition="outside",
            hovertemplate="%{y}: %{x:.1f}<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=10, r=40, t=10, b=10),
        height=max(280, 28 * len(plot_df) + 60),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans", color="#12202c"),
        xaxis=dict(title="MTF Score", range=[-110, 110], zeroline=True, zerolinecolor="#94a3b8"),
        yaxis=dict(title=""),
    )
    return fig


def build_price_chart(summary: dict, focus_tf: str) -> go.Figure:
    raw_rows = summary.get("_raw_rows") or []
    series = None
    for r in raw_rows:
        if r.get("interval") == focus_tf and r.get("series") is not None:
            series = r["series"]
            break
    if series is None:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=series.index,
            open=series["Open"],
            high=series["High"],
            low=series["Low"],
            close=series["Close"],
            name="Price",
            increasing_line_color="#0f7a5a",
            decreasing_line_color="#b42318",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=series.index,
            y=series["AlphaTrend"],
            name="AlphaTrend",
            line=dict(color="#1f6f8b", width=2.5),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=series.index,
            y=series["AlphaTrend_2"],
            name="AT[2]",
            line=dict(color="#c45c26", width=1.5, dash="dot"),
        )
    )
    buys = series[series["buy_signal"]]
    sells = series[series["sell_signal"]]
    if not buys.empty:
        fig.add_trace(
            go.Scatter(
                x=buys.index,
                y=buys["Low"] * 0.995,
                mode="markers+text",
                text=["BUY"] * len(buys),
                textposition="bottom center",
                marker=dict(symbol="triangle-up", size=12, color="#1f6f8b"),
                name="BUY",
            )
        )
    if not sells.empty:
        fig.add_trace(
            go.Scatter(
                x=sells.index,
                y=sells["High"] * 1.005,
                mode="markers+text",
                text=["SELL"] * len(sells),
                textposition="top center",
                marker=dict(symbol="triangle-down", size=12, color="#7a1f1f"),
                name="SELL",
            )
        )
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        height=420,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.35)",
        font=dict(family="DM Sans", color="#12202c"),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        title=f"{summary['symbol']} · {focus_tf}",
    )
    return fig


def sidebar_controls():
    st.sidebar.markdown("### Scan settings")
    universe = st.sidebar.radio(
        "Universe",
        options=["NSE F&O (all)", "Custom symbols"],
        index=0,
        help="Moto: validate AlphaTrend across every NSE F&O equity",
    )
    symbols_raw = st.sidebar.text_area(
        "Symbols",
        value=",".join(DEFAULT_SYMBOLS),
        height=100,
        help="Comma-separated tickers (used when Custom symbols is selected)",
        disabled=universe.startswith("NSE"),
    )
    refresh_fno = st.sidebar.checkbox("Refresh F&O list from NSE", value=False)
    limit = st.sidebar.number_input(
        "Limit (0 = all)",
        min_value=0,
        max_value=500,
        value=0,
        step=10,
        help="Cap symbol count for faster smoke runs",
    )
    default_tf = list(DEFAULT_MTF_FRAMES)
    timeframes = st.sidebar.multiselect(
        "Timeframes",
        options=["5m", "15m", "1h", "4h", "1d", "1wk"],
        default=default_tf,
        help="5m included for short-term trend; signals use closed bars by default",
    )
    multiplier = st.sidebar.slider("Multiplier (coeff)", 0.5, 3.0, 1.0, 0.1)
    ap = st.sidebar.slider("Common period (AP)", 5, 50, 14, 1)
    lookback = st.sidebar.slider("Signal lookback (bars)", 1, 20, 3, 1)
    no_volume = st.sidebar.checkbox("No volume (RSI gate)", value=False)
    include_forming = st.sidebar.checkbox(
        "Include forming bar (live/unconfirmed)",
        value=False,
        help="Default off: 5m/15m/1h only use fully closed candles",
    )
    workers = st.sidebar.slider("Workers", 1, 8, 4)
    run = st.sidebar.button("Run MTF scan", type="primary", use_container_width=True)

    if universe.startswith("NSE"):
        try:
            symbols = fno_yahoo_tickers(refresh=refresh_fno)
            if limit:
                symbols = symbols[: int(limit)]
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(f"F&O list failed: {exc}")
            symbols = parse_symbols(symbols_raw.replace("\n", ","), None)
    else:
        symbols = parse_symbols(symbols_raw.replace("\n", ","), None)

    return {
        "symbols": symbols,
        "timeframes": timeframes or default_tf,
        "multiplier": multiplier,
        "ap": ap,
        "lookback": lookback,
        "no_volume": no_volume,
        "include_forming": include_forming,
        "workers": workers,
        "run": run,
        "universe": universe,
    }


def main() -> None:
    st.markdown(
        """
<div class="brand-wrap">
  <p class="brand">AlphaTrend</p>
  <p class="brand-sub">NSE F&amp;O signal desk — validate AlphaTrend on closed 5m/15m/1h candles across the full derivatives universe. Hover heatmap cells for signal time · copy tickers below the watchlist.</p>
</div>
""",
        unsafe_allow_html=True,
    )

    cfg = sidebar_controls()
    if "summaries" not in st.session_state:
        st.session_state.summaries = None
        st.session_state.cfg = None

    if cfg["run"]:
        with st.spinner(f"Scanning {len(cfg['symbols'])} symbols × {len(cfg['timeframes'])} frames…"):
            summaries = scan_universe_mtf(
                cfg["symbols"],
                timeframes=cfg["timeframes"],
                multiplier=cfg["multiplier"],
                ap=cfg["ap"],
                no_volume=cfg["no_volume"],
                lookback=cfg["lookback"],
                workers=cfg["workers"],
                include_forming=cfg["include_forming"],
            )
            # Re-fetch one symbol detail with series kept for chart (already in _raw_rows)
            st.session_state.summaries = summaries
            st.session_state.cfg = cfg

    summaries = st.session_state.summaries
    if not summaries:
        st.info("Set symbols & timeframes in the sidebar, then click **Run MTF scan**.")
        return

    active_cfg = st.session_state.cfg or cfg
    frames = active_cfg["timeframes"]
    pm = portfolio_metrics(summaries)
    metric_strip(pm)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    st.caption(
        f"Updated {now} · universe={active_cfg.get('universe', 'custom')} · "
        f"symbols={len(active_cfg['symbols'])} · coeff={active_cfg['multiplier']} · "
        f"AP={active_cfg['ap']} · lookback={active_cfg['lookback']} · "
        f"gate={'RSI' if active_cfg['no_volume'] else 'MFI'} · "
        f"bars={'forming' if active_cfg.get('include_forming') else 'closed'} · "
        f"frames={', '.join(frames)}"
    )

    table = summaries_to_frame(summaries, frames)

    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("Confluence heatmap")
        st.plotly_chart(build_heatmap(summaries, frames), use_container_width=True)
    with right:
        st.subheader("MTF score by symbol")
        st.plotly_chart(build_score_bar(table), use_container_width=True)

    st.subheader("Watchlist numbers")
    show = table.copy()
    # Prefer copy-friendly ticker first, then Yahoo symbol
    base_cols = [
        "ticker",
        "symbol",
        "mtf_score",
        "bias",
        "alignment_pct",
        "bull_tf",
        "bear_tf",
        "buy_tf",
        "sell_tf",
        "avg_dist_pct",
        "close",
    ]
    # Keep trend/signal/time columns in a readable order per TF
    extra = []
    for tf in frames:
        for suffix in ("_trend", "_signal", "_fresh", "_signal_time", "_trend_since", "_dist"):
            col = f"{tf}{suffix}"
            if col in show.columns:
                extra.append(col)
    leftover = [c for c in show.columns if c not in base_cols and c not in extra]
    show = show[[c for c in base_cols + extra + leftover if c in show.columns]]

    st.caption(
        "NEW = signal on the latest closed bar · “N bar(s) ago” = still inside lookback but older. "
        "trend_since = when the current UP/DOWN direction started."
    )
    st.dataframe(
        show.style.format(
            {
                "mtf_score": "{:.1f}",
                "alignment_pct": "{:.1f}",
                "avg_dist_pct": "{:.2f}",
                "close": "{:.2f}",
            },
            na_rep="—",
        ),
        use_container_width=True,
        hide_index=True,
        height=min(420, 48 + 35 * min(len(show), 12)),
        column_config={
            "ticker": st.column_config.TextColumn("ticker", help="Bare name — select cell and Ctrl+C"),
            "symbol": st.column_config.TextColumn("symbol", help="Yahoo ticker e.g. RELIANCE.NS"),
        },
    )

    # Easy live copy of names (Streamlit tables are awkward to multi-select)
    st.markdown("##### Copy stock names")
    copy_mode = st.radio(
        "Copy list",
        options=["Active signals only", "All scanned", "Selected symbol"],
        horizontal=True,
        label_visibility="collapsed",
    )
    active_syms = [
        s["symbol"]
        for s in summaries
        if (s.get("buy_tf") or 0) > 0 or (s.get("sell_tf") or 0) > 0
    ]
    if copy_mode.startswith("Active"):
        copy_syms = active_syms or [s["symbol"] for s in summaries[:20]]
    elif copy_mode.startswith("All"):
        copy_syms = [s["symbol"] for s in summaries]
    else:
        copy_syms = []  # filled after selectbox below — placeholder for now

    # Selected-symbol copy is wired after the detail picker; for other modes show now.
    if not copy_mode.startswith("Selected"):
        bare = [bare_ticker(s) for s in copy_syms]
        c_a, c_b = st.columns(2)
        with c_a:
            st.caption("Bare tickers (broker paste) — click text, Ctrl+A, Ctrl+C")
            st.markdown(
                f'<div class="copy-box">{html.escape(", ".join(bare))}</div>',
                unsafe_allow_html=True,
            )
            st.text_area(
                "bare_copy",
                value="\n".join(bare),
                height=100,
                label_visibility="collapsed",
            )
        with c_b:
            st.caption("Yahoo symbols (.NS)")
            st.markdown(
                f'<div class="copy-box">{html.escape(", ".join(copy_syms))}</div>',
                unsafe_allow_html=True,
            )
            st.text_area(
                "yahoo_copy",
                value="\n".join(copy_syms),
                height=100,
                label_visibility="collapsed",
            )

    st.subheader("Symbol detail")
    symbols = [s["symbol"] for s in summaries]
    c1, c2 = st.columns([1, 1])
    with c1:
        pick = st.selectbox("Symbol", symbols)
    with c2:
        focus_tf = st.selectbox("Chart timeframe", frames, index=min(3, len(frames) - 1))

    # Selected-symbol copy panel
    if copy_mode.startswith("Selected"):
        bare_one = bare_ticker(pick)
        st.markdown("##### Copy selected")
        st.markdown(
            f'<div class="copy-box">{html.escape(bare_one)} &nbsp;&nbsp;|&nbsp;&nbsp; '
            f'{html.escape(pick)}</div>',
            unsafe_allow_html=True,
        )
        st.code(f"{bare_one}\n{pick}", language=None)

    summary = next(s for s in summaries if s["symbol"] == pick)

    # If series missing (shouldn't be), refresh one symbol
    if not summary.get("_raw_rows"):
        summary = analyze_symbol_mtf(
            pick,
            timeframes=frames,
            multiplier=active_cfg["multiplier"],
            ap=active_cfg["ap"],
            no_volume=active_cfg["no_volume"],
            lookback=active_cfg["lookback"],
            workers=active_cfg["workers"],
            include_forming=active_cfg.get("include_forming", False),
        )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("MTF score", _fmt(summary.get("mtf_score"), 1))
    m2.metric("Bias", summary.get("bias") or "—")
    m3.metric("Alignment", _fmt(summary.get("alignment_pct"), 1, "%"))
    m4.metric("Bull / Bear TFs", f"{summary.get('bull_tf', 0)} / {summary.get('bear_tf', 0)}")
    m5.metric("Avg dist vs AT", _fmt(summary.get("avg_dist_pct"), 2, "%"))

    st.plotly_chart(build_price_chart(summary, focus_tf), use_container_width=True)

    tf_rows = []
    for tf in frames:
        cell = (summary.get("timeframes") or {}).get(tf) or {}
        tf_rows.append(
            {
                "timeframe": tf,
                "trend": "UP" if cell.get("trend_up") else ("DOWN" if cell.get("trend_up") is False else "—"),
                "trend_since (IST)": cell.get("trend_since_ist") or "—",
                "trend_bars": cell.get("trend_bars"),
                "signal": cell.get("signal"),
                "freshness": cell.get("freshness") or "—",
                "signal_time (IST)": cell.get("signal_time_ist") or "—",
                "last_bar (IST)": cell.get("last_bar_ist") or "—",
                "dist_pct": cell.get("dist_pct"),
                "atr_pct": cell.get("atr_pct"),
                "close": cell.get("close"),
                "alphatrend": cell.get("alphatrend"),
                "bar_ago": cell.get("bar_ago"),
            }
        )
    st.dataframe(pd.DataFrame(tf_rows), use_container_width=True, hide_index=True)

    csv = table.to_csv(index=False).encode("utf-8")
    c_dl, c_eod = st.columns(2)
    with c_dl:
        st.download_button("Download MTF CSV", csv, file_name="alphatrend_mtf.csv", mime="text/csv")
    with c_eod:
        if st.button("Save EOD report to reports/", use_container_width=True):
            paths = save_mtf_eod(
                summaries,
                frames,
                lookback=active_cfg["lookback"],
                base_dir="reports",
            )
            st.success("Saved:\n" + "\n".join(f"{k}: {v}" for k, v in paths.items()))


if __name__ == "__main__":
    main()
