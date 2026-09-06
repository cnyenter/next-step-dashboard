import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import math
import re
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 1. PAGE CONFIG, BRAND TOKENS, GLOBAL STYLE
# ==========================================
st.set_page_config(page_title="Next Step Trading", layout="wide")

GREEN, RED, BLUE, AMBER, PURPLE = "#26a69a", "#ef5350", "#2962ff", "#f0b90b", "#ab47bc"
BG, PANEL, PANEL2, LINE, TEXT, MUTED = "#0d1117", "#151b26", "#1a2230", "#232c3d", "#e6edf3", "#8b98a8"

GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
.stApp { background-color: #0d1117; }
.block-container { padding-top: 1rem; padding-bottom: 1rem; }
h1, h2, h3, h4 { font-family: 'Space Grotesk', sans-serif !important; letter-spacing: -0.01em; }
p, div, span { font-family: 'IBM Plex Sans', sans-serif; }
.ns-row { display: flex; flex-wrap: wrap; margin: 0 -4px; }
.ns-tile { flex: 1; min-width: 150px; background: #151b26; padding: 14px 16px; border: 1px solid #232c3d; border-radius: 8px; margin: 4px; }
.ns-label { color: #a8b6c6; font-size: 12.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; }
.ns-value { color: #e6edf3; font-size: 26px; font-weight: 600; margin-top: 5px; font-family: 'IBM Plex Mono', monospace; }
.ns-sub { color: #9fadbd; font-size: 12.5px; margin-top: 3px; font-family: 'IBM Plex Mono', monospace; }
.ns-panel { background: #151b26; border: 1px solid #232c3d; border-radius: 8px; padding: 16px 18px; margin-bottom: 8px; }
.ns-section { font-family: 'Space Grotesk', sans-serif; font-size: 16px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #cbd6e2; margin: 10px 0 10px 2px; }
.ns-radar-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.ns-radar-inner { min-width: 640px; }
@media (max-width: 640px) {
  .ns-tile { flex: 1 1 100%; min-width: 100%; }
  .ns-value { font-size: 23px; }
  .ns-section { font-size: 15px; }
}
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


import time

def _fetch_with_retry(fn, attempts=3, base_delay=1.5):
    """Yahoo rate-limits aggressively. Retry with backoff, then give up quietly."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    raise last

def fetch_history(ticker, **kwargs):
    return _fetch_with_retry(lambda: yf.Ticker(ticker).history(**kwargs))

def fetch_many_changes(tickers, start_str, end_str):
    """Percent change (first open -> last close) for many tickers in ONE request."""
    if not tickers:
        return {}
    out = {}
    try:
        data = _fetch_with_retry(lambda: yf.download(
            tickers=" ".join(tickers), start=start_str, end=end_str, interval="1d",
            group_by="ticker", auto_adjust=True, progress=False, threads=False))
    except Exception:
        return {}
    if data is None or len(data) == 0:
        return {}
    for t in tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if t not in data.columns.get_level_values(0):
                    continue
                sub = data[t].dropna(how="all")
            else:
                sub = data.dropna(how="all")
            if len(sub) < 1:
                continue
            o, c = float(sub["Open"].iloc[0]), float(sub["Close"].iloc[-1])
            if o:
                out[t] = (c / o - 1.0) * 100.0
        except Exception:
            continue
    return out

def fetch_many_last(tickers):
    """Latest close for many tickers in ONE request."""
    if not tickers:
        return {}
    out = {}
    try:
        data = _fetch_with_retry(lambda: yf.download(
            tickers=" ".join(tickers), period="5d", interval="1d",
            group_by="ticker", auto_adjust=True, progress=False, threads=False))
    except Exception:
        return {}
    if data is None or len(data) == 0:
        return {}
    for t in tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if t not in data.columns.get_level_values(0):
                    continue
                sub = data[t].dropna(how="all")
            else:
                sub = data.dropna(how="all")
            if len(sub):
                out[t] = float(sub["Close"].iloc[-1])
        except Exception:
            continue
    return out

def tile(label, value, sub="", color=TEXT):
    return ("<div class='ns-tile'><div class='ns-label'>" + label + "</div>"
            "<div class='ns-value' style='color:" + color + ";'>" + value + "</div>"
            "<div class='ns-sub'>" + sub + "</div></div>")

# Dates may be entered in more than one format across rows, so parse each value
# individually instead of letting pandas infer one format for the whole column.
_DATE_FORMATS = ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y", "%Y/%m/%d",
                 "%m-%d-%y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y", "%d %b %Y")

def parse_date_col(s):
    out = []
    for v in s:
        d = pd.NaT
        txt = "" if pd.isna(v) else str(v).strip()
        if txt:
            for fmt in _DATE_FORMATS:
                try:
                    d = pd.to_datetime(txt, format=fmt)
                    break
                except (ValueError, TypeError):
                    continue
            if pd.isna(d):
                try:
                    d = pd.to_datetime(txt, errors="coerce")
                except Exception:
                    d = pd.NaT
        out.append(d)
    return pd.Series(out, index=s.index)

def clean_str(v):
    """Blank for NaN/None; trimmed text otherwise. NaN is truthy, so `v or ""` is not safe."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()

def level_name(is_sup, bottom, top, label=""):
    txt = ("S " if is_sup else "R ")
    txt += "{:,.0f}".format(bottom) if abs(top - bottom) < 0.5 else "{:,.0f} – {:,.0f}".format(bottom, top)
    if label:
        txt += " (" + label + ")"
    return txt

# ==========================================
# 2. SIDEBAR NAVIGATION ROUTER
# ==========================================
st.sidebar.title("🧭 Navigation")
page_selection = st.sidebar.radio("Select View:", ["Live Cockpit", "Swing Book", "Weekly Recap"])
st.sidebar.divider()

# Database Connections (PASTE LINKS HERE)
SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?gid=0&single=true&output=csv"
MQ_ES_SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?gid=1464368299&single=true&output=csv"
MQ_SPX_SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?gid=818488226&single=true&output=csv"
SWING_SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?gid=74511324&single=true&output=csv"

# ==========================================
# PAGE 1: LIVE COCKPIT
# ==========================================
if page_selection == "Live Cockpit":

    st_autorefresh(interval=60000, key="data_refresh")   # only the live page needs to poll

    st.sidebar.title("🎛️ Dashboard Controls")
    selected_asset = st.sidebar.radio("Select Active Asset:", ["E-mini Futures (ES_F)", "S&P 500 Index (SPX)"])
    selected_timeframe = st.sidebar.selectbox("Select Candle Interval:", ["1-Minute", "5-Minute", "15-Minute", "1-Hour", "Daily"], index=2)
    ma_type = st.sidebar.radio("Moving Average Type:", ["EMA", "SMA"], horizontal=True)
    show_mas = st.sidebar.multiselect("Moving Averages on Chart:", ["8", "21", "50", "100"], default=["8", "21", "50"])

    if selected_asset == "E-mini Futures (ES_F)":
        active_ticker, asset_label = "ES=F", "ES_F"
    else:
        active_ticker, asset_label = "^SPX", "SPX"

    if "1-Minute" in selected_timeframe: api_interval, api_period = "1m", "5d"
    elif "5-Minute" in selected_timeframe: api_interval, api_period = "5m", "5d"
    elif "15-Minute" in selected_timeframe: api_interval, api_period = "15m", "5d"
    elif "1-Hour" in selected_timeframe: api_interval, api_period = "1h", "10d"
    else: api_interval, api_period = "1d", "3mo"

    st.title("Next Step Trading: Daily Live Cockpit (" + asset_label + ")")

    # ---- Data fetch ----
    @st.cache_data(ttl=50)
    def get_market_data(ticker, period, interval):
        main_asset = fetch_history(ticker, period=period, interval=interval)
        oil = fetch_history("CL=F", period="2d", interval="15m")
        vix = fetch_history("^VIX", period="2d", interval="15m")
        tf_15m = fetch_history(ticker, period="5d", interval="15m")
        tf_1h = fetch_history(ticker, period="1mo", interval="1h")
        tf_1d = fetch_history(ticker, period="6mo", interval="1d")
        return main_asset, oil, vix, tf_15m, tf_1h, tf_1d

    @st.cache_data(ttl=50)
    def get_basis_prices():
        out = {}
        for sym in ["ES=F", "^SPX"]:
            try:
                h = fetch_history(sym, period="1d", interval="1m")
                if not h.empty:
                    out[sym] = float(h["Close"].iloc[-1])
            except Exception:
                pass
        return out

    try:
        df_main, df_oil, df_vix, df_15m, df_1h, df_1d = get_market_data(active_ticker, api_period, api_interval)
    except Exception as e:
        if "RateLimit" in type(e).__name__ or "rate" in str(e).lower():
            st.warning("Yahoo Finance is rate-limiting requests right now. Wait a minute and reload.")
        else:
            st.warning("Market data could not be loaded right now. Wait a moment and reload.")
        st.stop()

    if df_main.empty:
        st.error("⚠️ Data temporarily unavailable.")
        st.stop()

    latest_price = float(df_main['Close'].iloc[-1])
    latest_vix = float(df_vix['Close'].iloc[-1]) if not df_vix.empty else 15.0
    daily_pct_move = (latest_vix / math.sqrt(252)) / 100
    expected_move_points = latest_price * daily_pct_move
    em_upper, em_lower = latest_price + expected_move_points, latest_price - expected_move_points

    # Change vs prior daily close
    chg_pct = None
    try:
        if len(df_1d) >= 2:
            chg_pct = (latest_price / float(df_1d['Close'].iloc[-2]) - 1.0) * 100.0
    except Exception:
        pass

    # Realized range today vs implied range
    range_used = None
    try:
        last_day = df_15m.index[-1].date()
        today_df = df_15m[[d.date() == last_day for d in df_15m.index]]
        t_high, t_low = float(today_df['High'].max()), float(today_df['Low'].min())
        if expected_move_points > 0:
            range_used = (t_high - t_low) / (2 * expected_move_points) * 100.0
    except Exception:
        pass

    # ES - SPX basis
    basis = None
    bp = get_basis_prices()
    if "ES=F" in bp and "^SPX" in bp:
        basis = bp["ES=F"] - bp["^SPX"]

    # ---- Vitals row ----
    price_color = TEXT if chg_pct is None else (GREEN if chg_pct >= 0 else RED)
    vit = tile(asset_label + " (Live)", "{:,.2f}".format(latest_price),
               ("" if chg_pct is None else "{:+.2f}% vs prior close".format(chg_pct)), price_color)
    vit += tile("Volatility Index (VIX)", "{:.2f}".format(latest_vix), "drives the implied range")
    vit += tile("Implied Daily Move", "± {:.1f} pts".format(expected_move_points),
                "{:,.0f} – {:,.0f}".format(em_lower, em_upper))
    if range_used is not None:
        ru_color = GREEN if range_used < 80 else (AMBER if range_used < 110 else RED)
        vit += tile("Range Used Today", "{:.0f}%".format(range_used), "of the implied range", ru_color)
    if basis is not None:
        vit += tile("ES – SPX Basis", "{:+.1f}".format(basis), "add to SPX levels for ES", BLUE)
    st.markdown("<div class='ns-row'>" + vit + "</div>", unsafe_allow_html=True)
    st.divider()

    # ---- Published levels from sheet ----
    levels_note = ""
    levels_asof = None
    try:
        levels_df = pd.read_csv(SHEET_URL)
        filtered_levels = levels_df[levels_df['Ticker'] == active_ticker].copy()
        # With a Date column present, show only the latest published set (not the whole archive)
        if "Date" in filtered_levels.columns and not filtered_levels.empty:
            filtered_levels["_dt"] = parse_date_col(filtered_levels["Date"])
            if filtered_levels["_dt"].notna().any():
                levels_asof = filtered_levels["_dt"].max()
                filtered_levels = filtered_levels[filtered_levels["_dt"] == levels_asof]
    except Exception:
        filtered_levels = pd.DataFrame()
        levels_note = "Levels sheet unavailable — zones and ladder hidden."
    if levels_note:
        st.caption(levels_note)
    elif levels_asof is not None:
        st.caption("Levels as published " + levels_asof.strftime("%b %d, %Y"))

    # ---- MenthorQ dealer levels ----
    active_mq_url = MQ_ES_SHEET_URL if active_ticker == "ES=F" else MQ_SPX_SHEET_URL
    mq_dict = {}
    try:
        mq_df = pd.read_csv(active_mq_url, header=None)
        if not mq_df.empty:
            mq_paste = mq_df.to_string(header=False, index=False)
            for line in mq_paste.split('\n'):
                if not line.strip(): continue
                numbers = re.findall(r'[\d,]+\.?\d*', line)
                if numbers:
                    val_str = numbers[-1]
                    val = float(val_str.replace(',', ''))
                    name = line.rsplit(val_str, 1)[0].strip()
                    mq_dict[name] = val
    except Exception:
        pass

    call_res = next((v for k, v in mq_dict.items() if "Call Resistance" in k and "0DTE" not in k), None)
    put_sup = next((v for k, v in mq_dict.items() if "Put Support" in k and "0DTE" not in k), None)
    hvl = next((v for k, v in mq_dict.items() if "HVL" in k or "High Vol Level" in k), None)
    dte_call = next((v for k, v in mq_dict.items() if "0DTE Call" in k), None)
    dte_put = next((v for k, v in mq_dict.items() if "0DTE Put" in k), None)
    range_high = next((v for k, v in mq_dict.items() if "1D Max" in k), None)
    range_low = next((v for k, v in mq_dict.items() if "1D Min" in k), None)

    # ---- Dealer Proximity Radar (HTML, matches Swing Book ladder language) ----
    if call_res and put_sup:
        st.markdown("<div class='ns-section'>🎯 Dealer Proximity Radar (" + asset_label + ")</div>", unsafe_allow_html=True)

        marks = [("1D Min", range_low, MUTED), ("0DTE Put", dte_put, GREEN), ("Put Support", put_sup, GREEN),
                 ("HVL", hvl, AMBER), ("Call Res", call_res, RED), ("0DTE Call", dte_call, RED), ("1D Max", range_high, MUTED)]
        marks = [(n, float(v), c) for (n, v, c) in marks if v is not None]
        marks.sort(key=lambda m: m[1])

        all_vals = [v for _, v, _ in marks] + [latest_price]
        lo, hi = min(all_vals) - 15.0, max(all_vals) + 15.0
        span = hi - lo

        def rpct(v):
            return max(0.0, min(100.0, (v - lo) / span * 100.0))

        zones = ""
        zones += "<div style='position:absolute; top:44px; left:0; width:" + "{:.1f}".format(rpct(put_sup)) + "%; height:6px; background:rgba(38,166,154,0.28); border-radius:3px;'></div>"
        zones += "<div style='position:absolute; top:44px; left:" + "{:.1f}".format(rpct(call_res)) + "%; right:0; height:6px; background:rgba(239,83,80,0.28); border-radius:3px;'></div>"

        lp_pct = rpct(latest_price)
        MIN_GAP = 13.0         # % of track width needed between labels sharing a lane
        LIVE_GAP = 12.0        # clearance required around the live price tag (lane 0)
        # lane 0 = above track, lanes 1 and 2 = stacked below it
        lane_top = {0: 0, 1: 50, 2: 78}
        last_x = {0: -999.0, 1: -999.0, 2: -999.0}

        mk = ""
        for name, val, color in marks:
            x_val = rpct(val)
            lane = None
            for cand in (0, 1, 2):
                if x_val - last_x[cand] < MIN_GAP:
                    continue
                if cand == 0 and abs(x_val - lp_pct) < LIVE_GAP:
                    continue
                lane = cand
                break
            if lane is None:
                # nothing clear: take the lane with the most room, never lane 0 near the live tag
                options = [c for c in (0, 1, 2) if not (c == 0 and abs(x_val - lp_pct) < LIVE_GAP)]
                lane = max(options, key=lambda c: x_val - last_x[c])
            last_x[lane] = x_val
            x = "{:.1f}".format(x_val)

            if lane == 0:
                mk += ("<div style='position:absolute; left:" + x + "%; top:0; transform:translateX(-50%); text-align:center; width:96px;'>"
                       "<div style='color:" + color + "; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>" + name + "</div>"
                       "<div style='color:" + TEXT + "; font-family:IBM Plex Mono,monospace; font-size:14px; font-weight:600;'>" + "{:,.0f}".format(val) + "</div>"
                       "<div style='width:2px; height:14px; background:" + color + "; margin:2px auto 0;'></div></div>")
            else:
                connector = "" if lane == 1 else "<div style='width:2px; height:28px; background:" + color + "; opacity:0.55; margin:0 auto;'></div>"
                mk += ("<div style='position:absolute; left:" + x + "%; top:" + str(lane_top[lane]) + "px; transform:translateX(-50%); text-align:center; width:96px;'>"
                       + connector +
                       "<div style='width:2px; height:14px; background:" + color + "; margin:0 auto 2px;'></div>"
                       "<div style='color:" + TEXT + "; font-family:IBM Plex Mono,monospace; font-size:14px; font-weight:600;'>" + "{:,.0f}".format(val) + "</div>"
                       "<div style='color:" + color + "; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>" + name + "</div></div>")

        lp = "{:.1f}".format(rpct(latest_price))
        mk += ("<div style='position:absolute; left:" + lp + "%; top:26px; transform:translateX(-50%); text-align:center; z-index:3;'>"
               "<div style='background:" + BLUE + "; color:white; font-family:IBM Plex Mono,monospace; font-size:14px; font-weight:600; padding:2px 8px; border-radius:4px; white-space:nowrap;'>" + "{:,.1f}".format(latest_price) + "</div>"
               "<div style='width:2px; height:18px; background:white; margin:1px auto 0;'></div></div>")

        radar = ("<div class='ns-panel' style='padding:14px 40px 10px;'>"
                 "<div class='ns-radar-scroll'><div class='ns-radar-inner' style='position:relative; height:136px;'>"
                 "<div style='position:absolute; top:44px; left:0; right:0; height:6px; background:#222a38; border-radius:3px;'></div>"
                 + zones + mk + "</div></div></div>")
        st.markdown(radar, unsafe_allow_html=True)

    # ---- Main price chart with MAs and published level zones ----
    fig = go.Figure(data=[go.Candlestick(x=df_main.index, open=df_main['Open'], high=df_main['High'], low=df_main['Low'], close=df_main['Close'],
                                         name=asset_label, increasing_line_color=GREEN, increasing_fillcolor=GREEN,
                                         decreasing_line_color=RED, decreasing_fillcolor=RED)])

    ma_colors = {"8": "#e6edf3", "21": BLUE, "50": AMBER, "100": PURPLE}
    for p in show_mas:
        n = int(p)
        if len(df_main) > n:
            if ma_type == "EMA":
                series = df_main['Close'].ewm(span=n, adjust=False).mean()
            else:
                series = df_main['Close'].rolling(window=n).mean()
            fig.add_trace(go.Scatter(x=df_main.index, y=series, mode='lines', name=p + ma_type,
                                     line=dict(color=ma_colors[p], width=1.3)))

    # --- Initial view is zoomed to the price action; ALL zones are drawn so zooming out reveals them ---
    p_hi, p_lo = float(df_main['High'].max()), float(df_main['Low'].min())
    pad = max((p_hi - p_lo) * 0.07, expected_move_points * 0.12)
    y_hi, y_lo = p_hi + pad, p_lo - pad

    all_zones = []
    for _, row in filtered_levels.iterrows():
        try:
            zone_type, bottom, top = row['Type'], float(row['Bottom']), float(row['Top'])
        except Exception:
            continue
        if bottom > top:
            bottom, top = top, bottom
        lbl = clean_str(row.get("Label"))
        all_zones.append((str(zone_type).strip().lower() == "support", bottom, top, lbl))

    # Stagger labels so stacked zones do not overprint each other
    all_zones.sort(key=lambda z: z[1])
    last_label_y, x_slots, slot = None, [0.005, 0.17, 0.34], 0
    full_span = max(y_hi - y_lo, 1.0)
    for is_sup, bottom, top, lbl in all_zones:
        fill_color = GREEN if is_sup else RED
        mid = (bottom + top) / 2.0
        if last_label_y is not None and abs(mid - last_label_y) < full_span * 0.05:
            slot = (slot + 1) % len(x_slots)
        else:
            slot = 0
        last_label_y = mid
        zone_label = level_name(is_sup, bottom, top, lbl)
        fig.add_hrect(y0=bottom, y1=top, line_width=1, line_color=fill_color,
                      fillcolor=fill_color, opacity=0.16, layer="below")
        fig.add_annotation(xref="paper", x=x_slots[slot], y=top, yanchor="top", xanchor="left",
                           text=zone_label,
                           showarrow=False, font=dict(color="white", size=12),
                           bgcolor="rgba(13,17,23,0.75)", borderpad=2)

    for y_val, tag in [(em_upper, "+1 SD"), (em_lower, "-1 SD")]:
        fig.add_hline(y=y_val, line_dash="dash", line_color="#00BFFF", line_width=1.2)
        fig.add_annotation(xref="paper", x=0.995, y=y_val, xanchor="right", yanchor="middle", text=tag,
                           showarrow=False, font=dict(color="white", size=12), bgcolor="#00BFFF", borderpad=3)

    fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=620,
                      yaxis=dict(side="right", range=[y_lo, y_hi], fixedrange=False, tickfont=dict(size=13)),
                      xaxis=dict(fixedrange=False, tickfont=dict(size=13)),
                      dragmode="pan",
                      paper_bgcolor=BG, plot_bgcolor="#10151f",
                      margin=dict(l=10, r=10, t=34, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                                  bgcolor="rgba(0,0,0,0)", font=dict(size=13)))
    st.plotly_chart(fig, theme=None, use_container_width=True,
                    config={"scrollZoom": True, "displaylogo": False,
                            "modeBarButtonsToRemove": ["select2d", "lasso2d"]})
    st.caption("Chart opens zoomed to the session. Scroll or drag to zoom out — every published level is plotted, including those outside the current view.")

    # ---- Distance to Your Levels ladder ----
    if not filtered_levels.empty:
        st.markdown("<div class='ns-section'>📏 Distance To The Published Levels "
                    "<span style='font-size:12.5px; font-weight:400; text-transform:none; letter-spacing:0; color:" + MUTED + ";'>"
                    "&nbsp;— points to the near edge of each zone</span></div>", unsafe_allow_html=True)
        rows = []
        for _, row in filtered_levels.iterrows():
            try:
                mid = (float(row['Bottom']) + float(row['Top'])) / 2.0
                rows.append((str(row['Type']).strip().title(), float(row['Bottom']), float(row['Top']), mid,
                             clean_str(row.get("Label"))))
            except Exception:
                continue
        above = sorted([r for r in rows if r[3] >= latest_price], key=lambda r: r[3])[:5]
        below = sorted([r for r in rows if r[3] < latest_price], key=lambda r: -r[3])[:5]

        def ladder_row(r, nearest):
            typ, bottom, top, mid, lbl = r
            color = GREEN if typ == "Support" else RED
            border = "border:1px solid " + (BLUE if nearest else LINE) + ";"
            zone = "{:,.0f}".format(mid) if abs(top - bottom) < 1 else "{:,.0f} – {:,.0f}".format(bottom, top)
            tag = ("<span style='color:" + MUTED + "; font-size:12px; margin-left:7px;'>" + lbl + "</span>") if lbl else ""
            in_zone = bottom <= latest_price <= top
            if in_zone:
                dist_html = ("<span style='margin-left:auto; font-family:IBM Plex Mono,monospace; font-size:14px; font-weight:600; "
                             "color:#0d1117; background:" + AMBER + "; padding:1px 8px; border-radius:4px;'>IN ZONE</span>")
            else:
                # Distance to the edge price would reach first, not the midpoint
                edge = top if mid < latest_price else bottom
                dist = edge - latest_price
                dist_html = ("<span style='margin-left:auto; font-family:IBM Plex Mono,monospace; font-size:15px; font-weight:600; color:"
                             + (GREEN if dist >= 0 else RED) + ";'>" + "{:+.1f} pts".format(dist) + "</span>")
            return ("<div style='display:flex; align-items:center; background:" + PANEL2 + "; " + border +
                    " border-radius:6px; padding:10px 14px; margin-bottom:7px;'>"
                    "<span style='width:10px; height:10px; border-radius:50%; background:" + color + "; margin-right:11px;'></span>"
                    "<span style='color:" + TEXT + "; font-size:15px;'>" + typ + " <span style='font-family:IBM Plex Mono,monospace; font-weight:600;'>" + zone + "</span>" + tag + "</span>"
                    + dist_html + "</div>")

        col_a, col_b = st.columns(2)
        with col_a:
            html = "<div class='ns-panel'><div class='ns-label' style='margin-bottom:8px;'>Overhead</div>"
            if above:
                for i, r in enumerate(reversed(above)):
                    html += ladder_row(r, nearest=(i == len(above) - 1))
            else:
                html += "<div style='color:" + MUTED + "; font-size:12px;'>No published levels overhead.</div>"
            html += "</div>"
            st.markdown(html, unsafe_allow_html=True)
        with col_b:
            html = "<div class='ns-panel'><div class='ns-label' style='margin-bottom:8px;'>Below</div>"
            if below:
                for i, r in enumerate(below):
                    html += ladder_row(r, nearest=(i == 0))
            else:
                html += "<div style='color:" + MUTED + "; font-size:12px;'>No published levels below.</div>"
            html += "</div>"
            st.markdown(html, unsafe_allow_html=True)

    st.divider()

    # ---- Multi-Timeframe Trend Confluence ----
    st.markdown("<div class='ns-section'>🧲 Trend Confluence Engine (Price vs Moving Averages)</div>", unsafe_allow_html=True)

    def analyze_trend(df):
        if df.empty or len(df) < 50: return "Data Insufficient", MUTED
        d = df.copy()
        d['SMA_20'] = d['Close'].rolling(window=20).mean()
        d['SMA_50'] = d['Close'].rolling(window=50).mean()
        curr, s20, s50 = d['Close'].iloc[-1], d['SMA_20'].iloc[-1], d['SMA_50'].iloc[-1]
        if curr > s20 and s20 > s50: return "Strong Bullish", GREEN
        elif curr < s20 and s20 < s50: return "Strong Bearish", RED
        elif curr > s20: return "Weak Bullish / Choppy", "#5c8d89"
        else: return "Weak Bearish / Choppy", "#b46a68"

    trends = [("15-Minute (Intraday)", *analyze_trend(df_15m)),
              ("1-Hour (Swing)", *analyze_trend(df_1h)),
              ("Daily (Macro)", *analyze_trend(df_1d))]
    tr_html = ""
    for name, label, color in trends:
        tr_html += ("<div class='ns-tile' style='text-align:center; border-bottom:4px solid " + color + ";'>"
                    "<div class='ns-label'>" + name + "</div>"
                    "<div style='color:" + color + "; font-size:17px; font-weight:600; margin-top:6px;'>" + label + "</div></div>")
    st.markdown("<div class='ns-row'>" + tr_html + "</div>", unsafe_allow_html=True)

    st.divider()

    # ---- Macro Risk Engine ----
    st.markdown("<div class='ns-section'>🌐 Macro Risk Engine (Crude Oil & VIX)</div>", unsafe_allow_html=True)
    macro_col1, macro_col2 = st.columns(2)

    def build_candlestick_mini(df, title):
        chg = ""
        try:
            c0, c1 = float(df['Close'].iloc[0]), float(df['Close'].iloc[-1])
            chg = "  ({:+.1f}%)".format((c1 / c0 - 1) * 100.0)
        except Exception:
            pass
        fig_mini = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
                                                  increasing_line_color=GREEN, increasing_fillcolor=GREEN,
                                                  decreasing_line_color=RED, decreasing_fillcolor=RED)])
        fig_mini.update_layout(title=dict(text=title + chg, font=dict(size=14, color="white")),
                               xaxis_rangeslider_visible=False, template="plotly_dark", height=330,
                               paper_bgcolor=BG, plot_bgcolor="#10151f",
                               margin=dict(l=10, r=10, t=40, b=10), yaxis=dict(side="right"))
        return fig_mini

    with macro_col1: st.plotly_chart(build_candlestick_mini(df_oil, "Crude Oil Futures (CL_F)"), theme=None, use_container_width=True)
    with macro_col2: st.plotly_chart(build_candlestick_mini(df_vix, "Volatility Index (VIX)"), theme=None, use_container_width=True)

    st.markdown("<p style='color:" + MUTED + "; font-size:11px; text-align:center; margin-top:10px;'>"
                "Prices via Yahoo Finance and may be delayed. This is not trading advice. This is purely for information/education.</p>",
                unsafe_allow_html=True)

# ==========================================
# PAGE 2: SWING BOOK
# ==========================================
elif page_selection == "Swing Book":

    st.title("📒 Next Step Trading: Swing Book")
    st.markdown("<p style='color: gray; font-size: 16px;'>Multi-day swing positions &middot; managed alongside the daily SPX / ES_F levels</p>", unsafe_allow_html=True)

    # ---- Book rules (edit these to your parameters) ----
    BOOK_OPENED = "Jul 2026"
    RISK_PER_TRADE = "1–2%"
    MAX_OPEN_POSITIONS = 6

    GREEN, RED, MUTED, PANEL, LINE = "#26a69a", "#ef5350", "#8b98a8", "#151b26", "#233"

    @st.cache_data(ttl=120)
    def load_swing_book(url):
        df = pd.read_csv(url)
        df = df.dropna(subset=["Ticker"])
        df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
        df["Status"] = df["Status"].astype(str).str.strip().str.upper()
        df["Side"] = df["Side"].astype(str).str.strip().str.title()
        return df

    @st.cache_data(ttl=300)
    def get_live_prices(tickers):
        # One batched request for every open position
        return fetch_many_last(list(tickers))

    try:
        book = load_swing_book(SWING_SHEET_URL)
    except Exception:
        st.info("Swing Book data unavailable. Check that SWING_SHEET_URL points to the published CSV of your SwingBook tab.")
        st.stop()

    open_df = book[book["Status"] == "OPEN"].copy()
    closed_df = book[book["Status"] == "CLOSED"].copy()

    # ---- Closed trade results ----
    def closed_result(row):
        try:
            e, x = float(row["Entry"]), float(row["Exit_Price"])
            return ((x - e) / e * 100.0) if row["Side"] == "Long" else ((e - x) / e * 100.0)
        except Exception:
            return None
    if not closed_df.empty:
        closed_df["Result %"] = closed_df.apply(closed_result, axis=1)
        closed_df = closed_df.dropna(subset=["Result %"])

    # ---- SPX benchmark ----
    @st.cache_data(ttl=900)
    def get_bench_daily(start_str):
        h = fetch_history("^SPX", start=start_str)
        if h.empty:
            return None
        h = h.copy()
        try:
            h.index = h.index.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        return h[["Close"]]

    def bench_px_on(hist, ts):
        """Closing price on the last index session at or before ts."""
        if hist is None or ts is None or pd.isna(ts):
            return None
        sub = hist[hist.index <= ts]
        if sub.empty:
            sub = hist  # trade dated before available history; fall back to first bar
            return float(sub["Close"].iloc[0])
        return float(sub["Close"].iloc[-1])

    for col in ["Date_Opened", "Date_Closed"]:
        if col in book.columns:
            book[col + "_dt"] = parse_date_col(book[col])
    for _df in (open_df, closed_df):
        for col in ["Date_Opened", "Date_Closed"]:
            if col in _df.columns:
                _df[col + "_dt"] = parse_date_col(_df[col])

    inception_dt = book["Date_Opened_dt"].min() if "Date_Opened_dt" in book.columns else None
    bench_hist = None
    if inception_dt is not None and pd.notna(inception_dt):
        try:
            bench_hist = get_bench_daily((inception_dt - pd.Timedelta(days=7)).strftime("%Y-%m-%d"))
        except Exception:
            bench_hist = None

    bench_since_inception = None
    if bench_hist is not None and inception_dt is not None and pd.notna(inception_dt):
        p0, p1 = bench_px_on(bench_hist, inception_dt), float(bench_hist["Close"].iloc[-1])
        if p0:
            bench_since_inception = (p1 / p0 - 1.0) * 100.0

    if not closed_df.empty and bench_hist is not None:
        def bench_over_trade(row):
            p0 = bench_px_on(bench_hist, row.get("Date_Opened_dt"))
            p1 = bench_px_on(bench_hist, row.get("Date_Closed_dt"))
            if not p0 or not p1:
                return None
            return (p1 / p0 - 1.0) * 100.0
        closed_df["SPX %"] = closed_df.apply(bench_over_trade, axis=1)
        closed_df["vs SPX"] = closed_df["Result %"] - closed_df["SPX %"]

    # ---- Scoreboard: rules until trades close, then live stats ----
    def tile(label, value, sub, color="white"):
        return (
            "<div style='flex:1; min-width:150px; background:" + PANEL + "; padding:14px 16px; "
            "border:1px solid " + LINE + "; border-radius:8px; margin:4px;'>"
            "<div style='color:" + MUTED + "; font-size:11px; text-transform:uppercase; letter-spacing:1px;'>" + label + "</div>"
            "<div style='color:" + color + "; font-size:22px; font-weight:bold; margin-top:4px;'>" + value + "</div>"
            "<div style='color:" + MUTED + "; font-size:11px; margin-top:2px;'>" + sub + "</div></div>"
        )

    if closed_df.empty:
        tiles = (
            tile("Book Opened", BOOK_OPENED, "tracked from trade #1")
            + tile("Risk Per Trade", RISK_PER_TRADE, "of allocated capital")
            + tile("Max Open", str(MAX_OPEN_POSITIONS), "positions at a time")
            + tile("Record", "0W — 0L", "every result logged, nothing hidden")
        )
        if bench_since_inception is not None:
            tiles += tile("SPX Since Inception", "%+.1f%%" % bench_since_inception, "the benchmark to beat",
                          GREEN if bench_since_inception >= 0 else RED)
    else:
        wins = closed_df[closed_df["Result %"] > 0]
        losses = closed_df[closed_df["Result %"] <= 0]
        n = len(closed_df)
        win_rate = len(wins) / n * 100.0
        avg_w = wins["Result %"].mean() if not wins.empty else 0.0
        avg_l = losses["Result %"].mean() if not losses.empty else 0.0
        total = closed_df["Result %"].sum()

        tiles = tile("Closed Trades", str(n), str(len(wins)) + "W — " + str(len(losses)) + "L")
        # A win rate off a handful of trades is noise, not a track record — say so.
        if n < 5:
            tiles += tile("Win Rate", "%.0f%%" % win_rate, "only %d trade%s — not meaningful yet" % (n, "" if n == 1 else "s"), MUTED)
        else:
            tiles += tile("Win Rate", "%.0f%%" % win_rate, "across %d closed trades" % n, GREEN if win_rate >= 50 else RED)
        tiles += tile("Avg Winner", "+%.1f%%" % avg_w, "vs %.1f%% avg loser" % avg_l, GREEN)
        tiles += tile("Sum of Results", "%+.1f%%" % total, "closed trades, unweighted", GREEN if total >= 0 else RED)

        if bench_since_inception is not None:
            tiles += tile("SPX Since Inception", "%+.1f%%" % bench_since_inception, "buy and hold, same window",
                          GREEN if bench_since_inception >= 0 else RED)
        if "vs SPX" in closed_df.columns and closed_df["vs SPX"].notna().any():
            avg_alpha = closed_df["vs SPX"].mean()
            beat = int((closed_df["vs SPX"] > 0).sum())
            tiles += tile("Avg Trade vs SPX", "%+.1f%%" % avg_alpha,
                          "beat SPX on %d of %d trades" % (beat, int(closed_df["vs SPX"].notna().sum())),
                          GREEN if avg_alpha >= 0 else RED)
    st.markdown("<div style='display:flex; flex-wrap:wrap;'>" + tiles + "</div>", unsafe_allow_html=True)
    st.divider()

    # ---- Open positions ----
    st.markdown("### Open Positions")
    if open_df.empty:
        st.info("No open positions. New entries appear here the moment the sheet updates.")
    else:
        live = get_live_prices(list(open_df["Ticker"].unique()))

        for _, row in open_df.iterrows():
            tkr, side = row["Ticker"], row["Side"]
            entry, stop = float(row["Entry"]), float(row["Stop"])
            targets = [float(row[t]) for t in ["T1", "T2", "T3"] if t in row and pd.notna(row[t]) and str(row[t]).strip() != ""]
            cur = live.get(tkr)
            sector = str(row.get("Sector", "")).strip()
            opened = str(row.get("Date_Opened", "")).strip()
            thesis = str(row.get("Thesis", "")).strip()

            is_long = side == "Long"
            side_color = GREEN if is_long else RED

            if cur is not None:
                pnl = (cur - entry) / entry * 100.0 if is_long else (entry - cur) / entry * 100.0
                pnl_color = GREEN if pnl >= 0 else RED
                bench = ""
                d0 = row.get("Date_Opened_dt")
                if bench_hist is not None and pd.notna(d0):
                    p0 = bench_px_on(bench_hist, d0)
                    if p0:
                        bench_r = (float(bench_hist["Close"].iloc[-1]) / p0 - 1.0) * 100.0
                        diff = pnl - bench_r
                        bench = ("<span style='color:" + MUTED + "; font-size:11px; font-weight:400; display:block; text-align:right;'>"
                                 "SPX %+.1f%% &middot; %+.1f%% vs SPX</span>" % (bench_r, diff))
                pnl_html = ("<span style='margin-left:auto; text-align:right;'>"
                            "<span style='font-weight:bold; font-size:16px; color:" + pnl_color + ";'>%+.1f%%</span>" % pnl
                            + bench + "</span>")
            else:
                pnl, pnl_color = None, MUTED
                pnl_html = "<span style='margin-left:auto; color:" + MUTED + "; font-size:12px;'>live price unavailable</span>"

            # Ladder geometry: 0% = stop, 100% = final target
            ladder_html = ""
            if targets:
                last_t = targets[-1]
                span = (last_t - stop) if is_long else (stop - last_t)
                if span and span > 0:
                    def pct(p):
                        raw = ((p - stop) / span * 100.0) if is_long else ((stop - p) / span * 100.0)
                        return max(0.0, min(100.0, raw))
                    def mark(p, label, color, lbl_style=""):
                        return ("<div style='position:absolute; left:" + "%.1f" % pct(p) + "%; top:0; transform:translateX(-50%); text-align:center; width:70px;'>"
                                "<div style='color:" + color + "; font-size:9px; text-transform:uppercase;'>" + label + "</div>"
                                "<div style='width:2px; height:12px; background:" + color + "; margin:2px auto;'></div>"
                                "<div style='color:white; font-size:11px; " + lbl_style + "'>" + ("%g" % p) + "</div></div>")
                    marks = mark(stop, "Stop", RED) + mark(entry, "Entry", "#cccccc")
                    for i, t in enumerate(targets):
                        marks += mark(t, "T" + str(i + 1), GREEN)
                    fill = ""
                    if cur is not None:
                        marks += mark(cur, "Live", pnl_color, "background:#2962ff; border-radius:3px; padding:0 4px; display:inline-block;")
                        a, b = sorted([pct(entry), pct(cur)])
                        fill = "<div style='position:absolute; top:32px; left:" + "%.1f" % a + "%; width:" + "%.1f" % (b - a) + "%; height:4px; background:" + pnl_color + "; border-radius:2px;'></div>"
                    ladder_html = ("<div style='position:relative; height:58px; margin:14px 30px 0;'>"
                                   "<div style='position:absolute; top:32px; left:0; right:0; height:4px; background:#222a38; border-radius:2px;'></div>"
                                   + fill + marks + "</div>")

            chips = "<span style='border:1px solid " + side_color + "; color:" + side_color + "; font-size:10px; padding:2px 8px; border-radius:4px; text-transform:uppercase; margin-right:6px;'>" + side + "</span>"
            if sector:
                chips += "<span style='border:1px solid #444; color:" + MUTED + "; font-size:10px; padding:2px 8px; border-radius:4px; margin-right:6px;'>" + sector + "</span>"
            if opened:
                chips += "<span style='border:1px solid #444; color:" + MUTED + "; font-size:10px; padding:2px 8px; border-radius:4px;'>Opened " + opened + "</span>"

            card = ("<div style='background:" + PANEL + "; border:1px solid " + LINE + "; border-radius:8px; padding:16px 18px; margin-bottom:14px;'>"
                    "<div style='display:flex; align-items:center; flex-wrap:wrap; gap:8px;'>"
                    "<span style='font-size:20px; font-weight:bold; letter-spacing:0.5px;'>" + tkr + "</span>" + chips + pnl_html + "</div>"
                    "<div style='color:" + MUTED + "; font-size:13px; margin-top:6px;'>" + thesis + "</div>"
                    + ladder_html + "</div>")
            st.markdown(card, unsafe_allow_html=True)

    st.divider()

    # ---- Closed trades ----
    st.markdown("### Closed Trades")
    if closed_df.empty:
        st.markdown("<div style='border:1px dashed #444; border-radius:8px; padding:16px; color:" + MUTED + "; font-size:13px;'>"
                    "The book is brand new — no closed trades yet. Every exit is logged here as it happens, winners and losers alike, starting with trade #1. "
                    "The scoreboard above switches to live performance stats once the first trades close.</div>", unsafe_allow_html=True)
    else:
        cd = closed_df.sort_values("Date_Closed_dt", ascending=False, na_position="last")
        has_spy = "vs SPX" in cd.columns and cd["vs SPX"].notna().any()

        head = ("<tr>"
                "<th style='text-align:left;'>Ticker</th><th style='text-align:left;'>Side</th>"
                "<th style='text-align:right;'>Entry</th><th style='text-align:right;'>Exit</th>"
                "<th style='text-align:left;'>Held</th><th style='text-align:right;'>Result</th>")
        if has_spy:
            head += "<th style='text-align:right;'>SPX</th><th style='text-align:right;'>vs SPX</th>"
        head += "</tr>"

        rows_html = ""
        for _, r in cd.iterrows():
            res = r["Result %"]
            res_c = GREEN if res >= 0 else RED
            d0, d1 = r.get("Date_Opened_dt"), r.get("Date_Closed_dt")
            if pd.notna(d0) and pd.notna(d1):
                held = "%s → %s" % (d0.strftime("%b %d"), d1.strftime("%b %d"))
            else:
                held = str(r.get("Date_Closed", ""))
            cells = ("<td style='font-weight:700;'>" + str(r["Ticker"]) + "</td>"
                     "<td style='color:" + MUTED + ";'>" + str(r["Side"]) + "</td>"
                     "<td style='text-align:right;'>" + "{:,.2f}".format(float(r["Entry"])) + "</td>"
                     "<td style='text-align:right;'>" + "{:,.2f}".format(float(r["Exit_Price"])) + "</td>"
                     "<td style='color:" + MUTED + ";'>" + held + "</td>"
                     "<td style='text-align:right; font-weight:600; color:" + res_c + ";'>" + "{:+.1f}%".format(res) + "</td>")
            if has_spy:
                sp, al = r.get("SPX %"), r.get("vs SPX")
                if pd.notna(sp):
                    al_c = GREEN if al >= 0 else RED
                    cells += ("<td style='text-align:right; color:" + MUTED + ";'>" + "{:+.1f}%".format(sp) + "</td>"
                              "<td style='text-align:right; font-weight:600; color:" + al_c + ";'>" + "{:+.1f}%".format(al) + "</td>")
                else:
                    cells += "<td style='text-align:right; color:" + MUTED + ";'>—</td><td style='text-align:right; color:" + MUTED + ";'>—</td>"
            rows_html += "<tr>" + cells + "</tr>"

        table = ("<style>"
                 ".ns-tbl{width:100%; border-collapse:collapse; background:#151b26; border:1px solid #232c3d;"
                 " border-radius:8px; overflow:hidden; font-size:14px; font-family:'IBM Plex Mono',monospace;}"
                 ".ns-tbl th{font-family:'IBM Plex Sans',sans-serif; font-size:11.5px; text-transform:uppercase;"
                 " letter-spacing:0.8px; color:#a8b6c6; padding:11px 14px; border-bottom:1px solid #232c3d; font-weight:600;}"
                 ".ns-tbl td{padding:10px 14px; border-bottom:1px solid #1c2434; color:#e6edf3;}"
                 ".ns-tbl tr:last-child td{border-bottom:none;}"
                 "</style><table class='ns-tbl'>" + head + rows_html + "</table>")
        st.markdown(table, unsafe_allow_html=True)
        if has_spy:
            st.caption("SPX shows what the index did over the same dates. "
                       "vs SPX is the difference — the value the trade added over simply owning the index.")

    # ---- Monthly performance vs SPX ----
    st.divider()
    st.markdown("<div class='ns-section'>📈 Performance vs SPX</div>", unsafe_allow_html=True)

    if closed_df.empty or closed_df["Date_Closed_dt"].notna().sum() == 0:
        st.markdown("<div style='border:1px dashed #444; border-radius:8px; padding:16px; color:" + MUTED + "; font-size:13.5px;'>"
                    "Monthly performance against SPX appears here once the first trades close.</div>", unsafe_allow_html=True)
    else:
        default_w = 100.0 / float(MAX_OPEN_POSITIONS)
        cd = closed_df.dropna(subset=["Date_Closed_dt"]).copy()
        cd["Month"] = cd["Date_Closed_dt"].dt.to_period("M")
        if "Weight_Pct" in cd.columns:
            w = pd.to_numeric(cd["Weight_Pct"], errors="coerce").fillna(default_w)
        else:
            w = pd.Series(default_w, index=cd.index)
        cd["Contribution"] = cd["Result %"] * (w / 100.0)
        book_monthly = cd.groupby("Month")["Contribution"].sum()

        idx_monthly = pd.Series(dtype=float)
        if bench_hist is not None and not bench_hist.empty:
            m_close = bench_hist["Close"].resample("ME").last()
            m_close.index = m_close.index.to_period("M")
            idx_monthly = (m_close.pct_change() * 100.0).dropna()
            first_m = m_close.index.min()
            if inception_dt is not None and pd.notna(inception_dt):
                p0 = bench_px_on(bench_hist, inception_dt)
                if p0 and first_m in m_close.index:
                    idx_monthly.loc[first_m] = (float(m_close.loc[first_m]) / p0 - 1.0) * 100.0
            idx_monthly = idx_monthly.sort_index()

        months = sorted(set(book_monthly.index) | set(idx_monthly.index))
        if months:
            labels = [str(m) for m in months]
            book_vals = [float(book_monthly.get(m, 0.0)) for m in months]
            idx_vals = [float(idx_monthly.get(m, 0.0)) for m in months]
            book_cum, idx_cum, be, ie = [], [], 1.0, 1.0
            for b, i in zip(book_vals, idx_vals):
                be *= (1 + b / 100.0); ie *= (1 + i / 100.0)
                book_cum.append((be - 1) * 100.0); idx_cum.append((ie - 1) * 100.0)

            pc1, pc2 = st.columns(2)
            with pc1:
                f1 = go.Figure()
                f1.add_trace(go.Bar(x=labels, y=idx_vals, name="SPX", marker_color="#7f8c9b"))
                f1.add_trace(go.Bar(x=labels, y=book_vals, name="Swing Book", marker_color=GREEN))
                f1.update_layout(title=dict(text="Month by month", font=dict(size=15, color="white")),
                                 barmode="group", template="plotly_dark", height=330,
                                 paper_bgcolor=BG, plot_bgcolor="#10151f",
                                 margin=dict(l=10, r=10, t=44, b=10),
                                 yaxis=dict(ticksuffix="%", tickfont=dict(size=12)),
                                 xaxis=dict(tickfont=dict(size=12)),
                                 legend=dict(orientation="h", y=1.0, x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=12)))
                st.plotly_chart(f1, theme=None, use_container_width=True)
            with pc2:
                f2 = go.Figure()
                f2.add_trace(go.Scatter(x=labels, y=idx_cum, name="SPX", mode="lines",
                                        line=dict(color="#7f8c9b", width=2)))
                f2.add_trace(go.Scatter(x=labels, y=book_cum, name="Swing Book", mode="lines",
                                        line=dict(color=GREEN, width=2.6)))
                f2.update_layout(title=dict(text="Cumulative", font=dict(size=15, color="white")),
                                 template="plotly_dark", height=330,
                                 paper_bgcolor=BG, plot_bgcolor="#10151f",
                                 margin=dict(l=10, r=10, t=44, b=10),
                                 yaxis=dict(ticksuffix="%", tickfont=dict(size=12)),
                                 xaxis=dict(tickfont=dict(size=12)),
                                 legend=dict(orientation="h", y=1.0, x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=12)))
                st.plotly_chart(f2, theme=None, use_container_width=True)

            rows_html = ""
            for lab, b, i, bc, ic in zip(labels, book_vals, idx_vals, book_cum, idx_cum):
                rows_html += ("<tr><td>" + lab + "</td>"
                              "<td style='text-align:right; color:" + (GREEN if i >= 0 else RED) + ";'>" + "{:+.2f}%".format(i) + "</td>"
                              "<td style='text-align:right; font-weight:600; color:" + (GREEN if b >= 0 else RED) + ";'>" + "{:+.2f}%".format(b) + "</td>"
                              "<td style='text-align:right; color:" + MUTED + ";'>" + "{:+.2f}%".format(ic) + "</td>"
                              "<td style='text-align:right; font-weight:600; color:" + (GREEN if bc >= 0 else RED) + ";'>" + "{:+.2f}%".format(bc) + "</td></tr>")
            st.markdown("<table class='ns-tbl'><tr>"
                        "<th style='text-align:left;'>Month</th>"
                        "<th style='text-align:right;'>SPX</th><th style='text-align:right;'>Book</th>"
                        "<th style='text-align:right;'>SPX cum.</th><th style='text-align:right;'>Book cum.</th>"
                        "</tr>" + rows_html + "</table>", unsafe_allow_html=True)

            n_months = len([m for m in months if m in book_monthly.index])
            method = ("Each closed trade is weighted at {:.1f}% of the book (an equal slice of {} maximum positions), "
                      "so a trade's contribution is its return times that weight — not the raw trade percentage. "
                      "Uninvested cash earns nothing. SPX is the price index over the same months."
                      ).format(default_w, MAX_OPEN_POSITIONS)
            if n_months < 3:
                method += " With only {} month{} of closed trades, treat these figures as a starting point rather than a track record.".format(
                    n_months, "" if n_months == 1 else "s")
            st.markdown("<div class='ns-panel' style='margin-top:10px; border-left:3px solid " + BLUE + ";'>"
                        "<span style='font-size:13px; color:#cdd8e4;'><strong>How this is calculated.</strong> " + method
                        + "</span></div>", unsafe_allow_html=True)

    st.markdown("<p style='color:" + MUTED + "; font-size:11px; text-align:center; margin-top:18px;'>"
                "This is not trading advice. This is purely for information/education. Positions reflect the author's own tracking portfolio.</p>", unsafe_allow_html=True)


# ==========================================
# PAGE 3: WEEKLY RECAP (auto-generated)
# ==========================================
elif page_selection == "Weekly Recap":

    st.title("Next Step Trading: The Tape Report")
    _title_ph = st.empty()   # product name is appended once the selection is known

    # Sector ETFs and the movers watchlist are fixed, so this page needs no weekly upkeep.
    SECTORS = {"XLK": "Technology", "XLF": "Financials", "XLE": "Energy", "XLV": "Health Care",
               "XLY": "Cons. Disc.", "XLP": "Cons. Staples", "XLI": "Industrials",
               "XLB": "Materials", "XLRE": "Real Estate", "XLU": "Utilities", "XLC": "Comm. Svcs"}
    WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX",
                 "JPM", "GS", "BAC", "V", "MA", "XOM", "CVX", "COP", "UNH", "LLY", "JNJ", "MRK",
                 "CAT", "BA", "GE", "WMT", "COST", "HD", "PG", "KO", "DIS", "CRM", "ORCL", "PLTR"]

    # Asset registry — add a row here to support another product later.
    # "peer" is the counterpart shown in the comparison tile; "futures" adds an overnight session block.
    WEEKLY_ASSETS = {
        "S&P 500 Index (SPX)":   dict(yf="^SPX",  sheet="^SPX",  label="SPX", peer="^NDX", peer_label="NDX", futures=False),
        "E-mini S&P (ES_F)":     dict(yf="ES=F",  sheet="ES=F",  label="ES",  peer="NQ=F", peer_label="NQ",  futures=True),
        "Nasdaq 100 (NDX)":      dict(yf="^NDX",  sheet="^NDX",  label="NDX", peer="^SPX", peer_label="SPX", futures=False),
        "Nasdaq Futures (NQ_F)": dict(yf="NQ=F",  sheet="NQ=F",  label="NQ",  peer="ES=F", peer_label="ES",  futures=True),
    }

    wk_col1, wk_col2 = st.columns([1, 2])
    with wk_col1:
        week_choice = st.radio("Week:", ["This week", "Last week"], horizontal=True)
    with wk_col2:
        asset_choice = st.radio("Product:", list(WEEKLY_ASSETS.keys()), horizontal=True)
    A = WEEKLY_ASSETS[asset_choice]
    _title_ph.markdown("<p style='color:" + MUTED + "; font-size:15px; margin-top:-10px;'>Showing <strong style='color:"
                       + TEXT + ";'>" + A["label"] + "</strong> — how the week traded, measured against the levels published before each open.</p>",
                       unsafe_allow_html=True)
    offset = 0 if week_choice == "This week" else 1
    try:
        today = pd.Timestamp.now(tz="US/Eastern").normalize()
    except Exception:
        today = pd.Timestamp.now().normalize()   # tzdata unavailable; fall back to naive time
    week_start = (today - pd.Timedelta(days=today.weekday())) - pd.Timedelta(weeks=offset)
    week_end = week_start + pd.Timedelta(days=4)
    # Is the selected week finished, and is today's session still open?
    try:
        now_et = pd.Timestamp.now(tz="US/Eastern")
    except Exception:
        now_et = pd.Timestamp.now()
    today_date = now_et.normalize().date()
    week_complete = today_date > week_end.date()
    session_open = (today_date <= week_end.date() and today_date >= week_start.date()
                    and now_et.weekday() < 5 and 9 <= now_et.hour < 16)

    range_txt = "Week of " + week_start.strftime("%b %d") + " – " + week_end.strftime("%b %d, %Y")
    if week_complete:
        st.markdown("<div style='background:" + PANEL + "; border:1px solid " + LINE + "; border-left:3px solid " + GREEN
                    + "; border-radius:0 8px 8px 0; padding:11px 15px; margin-bottom:6px;'>"
                    "<span style='font-size:13.5px; color:#cdd8e4;'><strong>" + range_txt + " — complete.</strong> "
                    "All five sessions are settled; nothing below will change.</span></div>", unsafe_allow_html=True)
    else:
        done = [d.strftime("%a") for d in pd.date_range(week_start, min(now_et.normalize(), week_end)) if d.weekday() < 5]
        partial = ""
        if session_open and done:
            partial = (" <strong>" + done[-1] + " is still trading</strong>, so today's column, the price profile "
                       "and the movers all move with the tape.")
        elif done:
            partial = " " + done[-1] + " has settled; the rest of the week is still to come."
        st.markdown("<div style='background:" + PANEL + "; border:1px solid " + LINE + "; border-left:3px solid " + AMBER
                    + "; border-radius:0 8px 8px 0; padding:11px 15px; margin-bottom:6px;'>"
                    "<span style='font-size:13.5px; color:#cdd8e4;'><strong>Week to date — " + range_txt + ".</strong> "
                    "Every section below covers Monday's open through the latest print, not a finished week."
                    + partial + " Publish from the completed week for final numbers.</span></div>",
                    unsafe_allow_html=True)
    st.caption("Generated automatically from the published levels and market data · prices refresh every 15 minutes")

    @st.cache_data(ttl=900)
    def get_week_bars(ticker, start_str, end_str):
        h = fetch_history(ticker, start=start_str, end=end_str, interval="15m")
        if h.empty:
            return None
        try:
            h.index = h.index.tz_convert("US/Eastern")
        except (TypeError, AttributeError):
            pass
        return h

    @st.cache_data(ttl=1800)
    def get_week_change(tickers, start_str, end_str):
        # One batched request for the whole list instead of one call per ticker
        return fetch_many_changes(list(tickers), start_str, end_str)

    s_str = week_start.strftime("%Y-%m-%d")
    e_str = (week_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        bars = get_week_bars(A["yf"], s_str, e_str)
    except Exception as e:
        bars = None
        if "RateLimit" in type(e).__name__ or "rate" in str(e).lower():
            st.warning("Yahoo Finance is rate-limiting requests right now. Wait a minute and reload — "
                       "the data is cached for 15 minutes once it loads.")
        else:
            st.warning("Market data could not be loaded right now. Wait a moment and reload.")
        st.stop()
    peer_daily = get_week_change([A["peer"]], s_str, e_str)

    if bars is None or bars.empty:
        st.info("Market data for this week isn't available yet. Intraday history is limited to roughly the last 60 days.")
        st.stop()

    daily = bars.resample("1D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    daily = daily[daily.index.dayofweek < 5]

    # ---------- Verdict tiles ----------
    wk_open, wk_close = float(daily["Open"].iloc[0]), float(daily["Close"].iloc[-1])
    wk_pct = (wk_close / wk_open - 1.0) * 100.0
    wk_range = float(daily["High"].max() - daily["Low"].min())

    tiles = tile(A["label"] + " On The Week", "{:+.1f}%".format(wk_pct),
                 "{:,.0f} → {:,.0f}".format(wk_open, wk_close), GREEN if wk_pct >= 0 else RED)
    if A["peer"] in peer_daily:
        peer_pct = peer_daily[A["peer"]]
        tiles += tile(A["peer_label"] + " On The Week", "{:+.1f}%".format(peer_pct),
                      "led " + A["label"] if abs(peer_pct) > abs(wk_pct) else "lagged " + A["label"],
                      GREEN if peer_pct >= 0 else RED)
    tiles += tile("Weekly Range", "{:,.0f} pts".format(wk_range),
                  "{:,.0f} low → {:,.0f} high".format(float(daily["Low"].min()), float(daily["High"].max())))

    # ---------- 1. Level Report Card (auto-graded) ----------
    show_untested = st.checkbox("Show levels that were never tested this week", value=False,
                                help="Off by default so the card stays readable. Levels price never reached are hidden.")
    def grade_level(is_support, bottom, top, d_high, d_low, d_close):
        if is_support:
            if d_low > top: return "none"
            if d_close < bottom: return "break"
            if d_low < bottom and d_close >= bottom: return "both"
            return "hold"
        if d_high < bottom: return "none"
        if d_close > top: return "break"
        if d_high > top and d_close <= top: return "both"
        return "hold"

    try:
        lv = pd.read_csv(SHEET_URL)
        lv = lv[lv["Ticker"].astype(str).str.strip() == A["sheet"]]
        if "Date" in lv.columns:
            lv["_dt"] = parse_date_col(lv["Date"]).dt.normalize()
    except Exception:
        lv = pd.DataFrame()

    card_html, tested, held = "", 0, 0
    ma_tested = ma_held = st_tested = st_held = 0
    has_dates = (not lv.empty) and ("_dt" in lv.columns) and lv["_dt"].notna().any()
    n_rows_all = 0

    if not lv.empty:
        raw = []
        for _, r in lv.iterrows():
            try:
                b, t = float(r["Bottom"]), float(r["Top"])
            except Exception:
                continue
            if b > t:
                b, t = t, b
            raw.append(dict(sup=str(r["Type"]).strip().lower() == "support", b=b, t=t,
                            lbl=clean_str(r.get("Label")),
                            d=(r["_dt"].date() if (has_dates and pd.notna(r.get("_dt"))) else None)))

        # A level that drifts a point or two day to day is ONE level, not several.
        # Cluster overlapping (or nearly touching) zones on the same side into one row.
        clusters = []
        for side in (True, False):
            items = sorted([x for x in raw if x["sup"] == side], key=lambda x: (x["b"] + x["t"]) / 2.0)
            cur = None
            for it in items:
                tol = max(3.0, ((it["b"] + it["t"]) / 2.0) * 0.0004)
                if cur is not None and it["b"] <= cur["t"] + tol:
                    cur["b"] = min(cur["b"], it["b"])
                    cur["t"] = max(cur["t"], it["t"])
                    cur["members"].append(it)
                else:
                    if cur is not None:
                        clusters.append(cur)
                    cur = dict(sup=side, b=it["b"], t=it["t"], members=[it])
            if cur is not None:
                clusters.append(cur)
        clusters.sort(key=lambda c: -c["t"])
        n_rows_all = len(clusters)

        style_map = {"hold": ("rgba(38,166,154,.22)", GREEN, "HELD"), "break": ("rgba(239,83,80,.22)", RED, "BRK"),
                     "both": ("rgba(240,185,11,.20)", AMBER, "B/R"), "none": ("#141a24", "#3d4757", "\u2014"),
                     "unpub": ("transparent", "#2b3444", "\u00b7")}

        # Grade every cluster first, then decide which rows are worth showing
        graded_rows = []
        for c in clusters:
            labels_seen = [m["lbl"] for m in c["members"] if m["lbl"]]
            lbl = max(set(labels_seen), key=labels_seen.count) if labels_seen else ""
            is_ma = lbl.upper().endswith("MA")
            cells, any_test = [], False
            for _, d in daily.iterrows():
                dt = d.name.date()
                if has_dates:
                    todays = [m for m in c["members"] if m["d"] == dt]
                else:
                    todays = c["members"]
                if not todays:
                    cells.append("unpub")
                    continue
                zb = min(m["b"] for m in todays)
                zt = max(m["t"] for m in todays)
                g = grade_level(c["sup"], zb, zt, float(d["High"]), float(d["Low"]), float(d["Close"]))
                cells.append(g)
                if g != "none":
                    any_test = True
                    tested += 1
                    if is_ma:
                        ma_tested += 1
                    else:
                        st_tested += 1
                    if g == "hold":
                        held += 1
                        if is_ma:
                            ma_held += 1
                        else:
                            st_held += 1
            graded_rows.append(dict(sup=c["sup"], b=c["b"], t=c["t"], lbl=lbl, cells=cells, tested=any_test))

        shown = graded_rows if show_untested else [r for r in graded_rows if r["tested"]]
        if not shown:
            shown = graded_rows

        head = "<tr><th style='text-align:left; width:230px;'>Published Level</th>"
        for d in daily.index:
            is_live = session_open and d.date() == today_date
            head += ("<th>" + d.strftime("%a")
                     + ("<div style='color:" + AMBER + "; font-size:9.5px; letter-spacing:0.4px; font-weight:600;'>LIVE</div>"
                        if is_live else "")
                     + "</th>")
        head += "</tr>"

        body = ""
        for r in shown:
            dot = GREEN if r["sup"] else RED
            row = ("<td class='lv'><span style='display:inline-block;width:8px;height:8px;border-radius:50%;background:"
                   + dot + ";margin-right:7px;'></span>" + level_name(r["sup"], r["b"], r["t"], r["lbl"]) + "</td>")
            for g in r["cells"]:
                bgc, fgc, txt = style_map[g]
                row += ("<td><span style='display:block;height:32px;line-height:32px;border-radius:5px;background:" + bgc
                        + ";color:" + fgc + ";font-family:IBM Plex Mono,monospace;font-size:14px;font-weight:600;'>" + txt + "</span></td>")
            body += "<tr>" + row + "</tr>"

        card_html = ("<style>.rc{width:100%;border-collapse:collapse}"
                     ".rc th{font-size:12.5px;text-transform:uppercase;letter-spacing:0.7px;color:" + MUTED
                     + ";padding:0 0 11px;font-weight:600;text-align:center}"
                     ".rc td{padding:5px 4px;text-align:center}"
                     ".rc td.lv{text-align:left;font-family:'IBM Plex Mono',monospace;font-size:15px;"
                     "white-space:nowrap;color:" + TEXT + "}"
                     "</style><table class='rc'>" + head + body + "</table>")

    if tested:
        tiles += tile("Levels Tested", "%d of %d" % (held, tested), "held on the day they were tested",
                      GREEN if held >= tested * 0.6 else AMBER)
    st.markdown("<div class='ns-row'>" + tiles + "</div>", unsafe_allow_html=True)
    st.divider()

    if card_html or lv.empty:
        st.markdown("<div class='ns-section'>📋 The Level Report Card</div>", unsafe_allow_html=True)
    if not card_html:
        st.markdown("<div style='border:1px dashed #444; border-radius:8px; padding:16px; color:" + MUTED + "; font-size:13.5px;'>"
                    "No published levels found for <strong>" + A["sheet"] + "</strong> in the levels sheet. "
                    "Add rows with that ticker and the report card will grade them automatically.</div>",
                    unsafe_allow_html=True)
    if card_html:
        st.markdown("<p class='ns-sub' style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                    "Graded automatically: HELD = tested and respected · BRK = closed through · B/R = broke intraday, closed back. "
                    "Levels that drift a point or two day to day are grouped into one row.</p>",
                    unsafe_allow_html=True)
        st.markdown("<div class='ns-panel'>" + card_html + "</div>", unsafe_allow_html=True)
        if ma_tested and st_tested:
            st.markdown("<div class='ns-panel' style='margin-top:8px; border-left:3px solid " + BLUE + ";'>"
                        "<span style='font-size:13.5px; color:#cdd8e4;'><strong>Moving-average levels held "
                        + "{:.0f}%".format(ma_held / ma_tested * 100) + "</strong> of the time they were tested ("
                        + str(ma_held) + " of " + str(ma_tested) + "), versus <strong>"
                        + "{:.0f}%".format(st_held / st_tested * 100) + "</strong> for structural levels ("
                        + str(st_held) + " of " + str(st_tested) + ").</span></div>", unsafe_allow_html=True)

    # ---------- 2. Where the week was fought (time at price) ----------
    st.markdown("<div class='ns-section'>📊 Where The Week Was Fought</div>", unsafe_allow_html=True)
    st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                "Share of 15-minute closes by price bucket — the prices that actually mattered. Builds through the week as bars print.</p>", unsafe_allow_html=True)
    bucket = max(5, round(wk_range / 12.0 / 5.0) * 5)
    closes = bars["Close"].dropna()
    b_idx = (closes / bucket).round().astype(int)
    counts = b_idx.value_counts().sort_index(ascending=False)
    peak = int(counts.max()) if not counts.empty else 1
    tap = ""
    for k, c in counts.items():
        px_lvl = k * bucket
        w = c / peak * 84.0   # leave room so the tag never clips at the panel edge
        tag = ""
        if c == peak:
            tag = ("<span style='margin-left:10px;font-family:IBM Plex Mono,monospace;font-size:12.5px;padding:1px 8px;"
                   "border-radius:3px;background:rgba(41,98,255,.2);color:#7aa2ff;white-space:nowrap;'>most-traded price</span>")
        tap += ("<div style='display:flex;align-items:center;height:24px;margin-bottom:4px;'>"
                "<div style='width:80px;font-family:IBM Plex Mono,monospace;font-size:14px;color:" + MUTED
                + ";text-align:right;padding-right:12px;'>" + "{:,.0f}".format(px_lvl) + "</div>"
                "<div style='flex:1;display:flex;align-items:center;min-width:0;'>"
                "<div style='height:18px;border-radius:3px;flex:none;width:" + "{:.1f}".format(w)
                + "%;background:linear-gradient(90deg,#2b6f6a,#26a69a);'></div>" + tag + "</div></div>")
    st.markdown("<div class='ns-panel'>" + tap + "</div>", unsafe_allow_html=True)

    # ---------- 3. When the money moved ----------
    st.markdown("<div class='ns-section'>🕐 When The Money Moved</div>", unsafe_allow_html=True)
    st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                "Net points by session block — where the week's trend actually got made.</p>", unsafe_allow_html=True)
    blocks = [("Open → 11a", 9, 11), ("Midday", 11, 14), ("2p → Close", 14, 16)]
    if A["futures"]:
        blocks = [("Overnight", 4, 9)] + blocks   # Globex into the RTH open
    days = list(daily.index)
    hm = "<div style='display:grid;grid-template-columns:118px repeat(" + str(len(days)) + ",1fr);gap:6px;'>"
    hm += "<div></div>"
    for d in days:
        _live = session_open and d.date() == today_date
        hm += ("<div style='font-size:12.5px;text-transform:uppercase;letter-spacing:0.7px;color:"
               + (AMBER if _live else MUTED)
               + ";text-align:center;font-weight:600;'>" + d.strftime("%a")
               + (" &bull; LIVE" if _live else "") + "</div>")
    cell_vals = {}
    for bname, h0, h1 in blocks:
        for d in days:
            seg = bars[(bars.index.date == d.date()) & (bars.index.hour >= h0) & (bars.index.hour < h1)]
            cell_vals[(bname, d)] = (float(seg["Close"].iloc[-1] - seg["Open"].iloc[0]) if len(seg) else None)
    mx = max([abs(v) for v in cell_vals.values() if v is not None] or [1.0])
    for bname, _, _ in blocks:
        hm += ("<div style='font-size:13.5px;color:" + MUTED + ";display:flex;align-items:center;justify-content:flex-end;"
               "padding-right:10px;'>" + bname + "</div>")
        for d in days:
            v = cell_vals[(bname, d)]
            if v is None:
                bgc, fgc, txt = "#141a24", "#3d4757", "—"
            else:
                inten = min(0.62, 0.10 + abs(v) / mx * 0.52)
                bgc = ("rgba(38,166,154,%.2f)" % inten) if v >= 0 else ("rgba(239,83,80,%.2f)" % inten)
                fgc = GREEN if v >= 0 else RED
                txt = "{:+.0f}".format(v)
            hm += ("<div style='height:44px;border-radius:6px;display:flex;align-items:center;justify-content:center;"
                   "background:" + bgc + ";color:" + fgc + ";font-family:IBM Plex Mono,monospace;font-size:15px;font-weight:600;'>"
                   + txt + "</div>")
    hm += "</div>"
    st.markdown("<div class='ns-panel'>" + hm + "</div>", unsafe_allow_html=True)

    # ---------- 4. Sector rotation ----------
    st.markdown("<div class='ns-section'>🔄 Sector Rotation</div>", unsafe_allow_html=True)
    st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                "Move from Monday\u2019s open to the latest print for the selected week.</p>", unsafe_allow_html=True)
    sec_chg = get_week_change(list(SECTORS.keys()), s_str, e_str)
    if sec_chg:
        smax = max([abs(v) for v in sec_chg.values()] or [1.0])
        rows = sorted(sec_chg.items(), key=lambda kv: -kv[1])
        srow = ""
        for tk, v in rows:
            w = abs(v) / smax * 46.0
            col = GREEN if v >= 0 else RED
            bar = ("<div style='position:absolute;left:50%;width:" + "{:.1f}".format(w) + "%;height:15px;background:" + col + ";border-radius:0 3px 3px 0;'></div>"
                   if v >= 0 else
                   "<div style='position:absolute;right:50%;width:" + "{:.1f}".format(w) + "%;height:15px;background:" + col + ";border-radius:3px 0 0 3px;'></div>")
            lab = ("<div style='position:absolute;left:calc(50% + " + "{:.1f}".format(w) + "% + 8px);font-family:IBM Plex Mono,monospace;font-size:13.5px;color:" + col + ";line-height:15px;'>" + "{:+.1f}%".format(v) + "</div>"
                   if v >= 0 else
                   "<div style='position:absolute;right:calc(50% + " + "{:.1f}".format(w) + "% + 8px);font-family:IBM Plex Mono,monospace;font-size:13.5px;color:" + col + ";line-height:15px;'>" + "{:+.1f}%".format(v) + "</div>")
            srow += ("<div style='display:flex;align-items:center;height:27px;'>"
                     "<div style='width:124px;font-size:14px;color:" + TEXT + ";'>" + SECTORS.get(tk, tk) + "</div>"
                     "<div style='flex:1;position:relative;height:15px;'>"
                     "<div style='position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:#2c3648;'></div>"
                     + bar + lab + "</div></div>")
        st.markdown("<div class='ns-panel'>" + srow + "</div>", unsafe_allow_html=True)

    # ---------- 5. Leaders and laggards ----------
    st.markdown("<div class='ns-section'>🏆 Leaders &amp; Laggards</div>", unsafe_allow_html=True)
    st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                "Biggest movers from Monday\u2019s open to the latest print — the board reshuffles as the week goes on.</p>", unsafe_allow_html=True)
    mv = get_week_change(WATCHLIST, s_str, e_str)
    if mv:
        ranked = sorted(mv.items(), key=lambda kv: -kv[1])
        leaders, laggards = ranked[:6], ranked[-6:][::-1]

        def mover_panel(title, items, color):
            h = ("<div class='ns-panel'><div style='font-size:11.5px;text-transform:uppercase;letter-spacing:0.8px;color:"
                 + MUTED + ";font-weight:600;margin-bottom:10px;'>" + title + "</div>")
            for tk, v in items:
                h += ("<div style='display:flex;align-items:center;background:" + PANEL2 + ";border:1px solid " + LINE
                      + ";border-radius:6px;padding:9px 13px;margin-bottom:6px;'>"
                      "<span style='font-family:Space Grotesk,sans-serif;font-weight:700;font-size:14px;'>" + tk + "</span>"
                      "<span style='margin-left:auto;font-family:IBM Plex Mono,monospace;font-size:14px;font-weight:600;color:"
                      + (GREEN if v >= 0 else RED) + ";'>" + "{:+.1f}%".format(v) + "</span></div>")
            return h + "</div>"

        mc1, mc2 = st.columns(2)
        with mc1:
            st.markdown(mover_panel("Leaders", leaders, GREEN), unsafe_allow_html=True)
        with mc2:
            st.markdown(mover_panel("Laggards", laggards, RED), unsafe_allow_html=True)

    st.markdown("<p style='color:" + MUTED + "; font-size:11.5px; text-align:center; margin-top:16px;'>"
                "This is not trading advice. This is purely for information/education.</p>", unsafe_allow_html=True)