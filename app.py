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

def fetch_many_closes(tickers, start_str, end_str):
    """DataFrame of daily closes (rows = dates, cols = tickers) in ONE request."""
    if not tickers:
        return None
    try:
        data = _fetch_with_retry(lambda: yf.download(
            tickers=" ".join(tickers), start=start_str, end=end_str, interval="1d",
            group_by="ticker", auto_adjust=True, progress=False, threads=False))
    except Exception:
        return None
    if data is None or len(data) == 0:
        return None
    cols = {}
    for t in tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if t not in data.columns.get_level_values(0):
                    continue
                s = data[t]["Close"]
            else:
                s = data["Close"]
            s = s.dropna()
            if len(s):
                cols[t] = s
        except Exception:
            continue
    if not cols:
        return None
    return pd.DataFrame(cols)

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
page_selection = st.sidebar.radio("Select View:", ["Live Cockpit", "Swing Book", "Weekly Recap", "Swing Screener"])
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

    @st.cache_data(ttl=120)
    def get_implied_spx_open():
        """Where SPX would open if you applied ES's move since the cash close.

        SPX levels get published before the cash market opens, so a gap can flip a
        level's role before the bell. ES trades through globex, so its move since
        Friday's 4pm print is the best available estimate of Monday's cash open.
        """
        try:
            spx_d = fetch_history("^SPX", period="5d", interval="1d")
            es_15 = fetch_history("ES=F", period="5d", interval="15m")
            if spx_d is None or spx_d.empty or es_15 is None or es_15.empty:
                return None
            spx_close = float(spx_d["Close"].iloc[-1])
            spx_date = spx_d.index[-1].date()
            try:
                es_15.index = es_15.index.tz_convert("US/Eastern")
            except (TypeError, AttributeError):
                pass
            ref = es_15[[(d.date() == spx_date and d.hour < 16) for d in es_15.index]]
            if ref.empty:
                return None
            es_ref = float(ref["Close"].iloc[-1])
            es_now = float(es_15["Close"].iloc[-1])
            gap = es_now - es_ref
            return dict(close=spx_close, gap=gap, implied=spx_close + gap, asof=spx_date)
        except Exception:
            return None

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

    imp = get_implied_spx_open()
    if imp is not None and abs(imp["gap"]) >= 0.5:
        gap_col = GREEN if imp["gap"] >= 0 else RED
        vit += tile("Implied SPX Open", "{:,.0f}".format(imp["implied"]),
                    "{:+.0f} vs the {} close ({:,.0f})".format(imp["gap"],
                                                               imp["asof"].strftime("%a"), imp["close"]),
                    gap_col)
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

    # Cash indices stop printing at 4pm, so while levels are being published overnight the
    # live price is a stale close. Compare the published levels against the implied open
    # instead: a support above that open will act as resistance when the bell rings.
    if (not filtered_levels.empty) and (not active_ticker.endswith("=F")) \
            and imp is not None and abs(imp["gap"]) >= 0.5:
        flipped_levels = []
        for _, _r in filtered_levels.iterrows():
            try:
                _b, _t = float(_r["Bottom"]), float(_r["Top"])
            except Exception:
                continue
            if _b > _t:
                _b, _t = _t, _b
            _mid = (_b + _t) / 2.0
            _sup = str(_r["Type"]).strip().lower() == "support"
            _above = _mid >= imp["implied"]
            if (_sup and _above) or ((not _sup) and not _above):
                _lbl = clean_str(_r.get("Label"))
                _nm = "{:,.0f}".format(_b) if abs(_t - _b) < 0.5 else "{:,.0f} – {:,.0f}".format(_b, _t)
                flipped_levels.append(("Support" if _sup else "Resistance") + " " + _nm
                                      + ((" (" + _lbl + ")") if _lbl else ""))
        if flipped_levels:
            st.markdown("<div class='ns-panel' style='border-left:3px solid " + AMBER + "; margin-top:6px;'>"
                        "<span style='font-size:13.5px; color:#cdd8e4;'><strong>"
                        + str(len(flipped_levels)) + " published level"
                        + ("" if len(flipped_levels) == 1 else "s")
                        + " will change role at the implied open of "
                        + "{:,.0f}".format(imp["implied"]) + ".</strong> "
                        + "; ".join(flipped_levels)
                        + ". A support above the open acts as resistance at the bell, and a resistance "
                          "below it acts as support.</span></div>", unsafe_allow_html=True)

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

    # ---- Exit legs: a trade can be scaled out at T1, T2 and a final exit ----
    def _num(v):
        try:
            if v is None or (isinstance(v, str) and not v.strip()):
                return None
            f = float(v)
            return None if pd.isna(f) else f
        except Exception:
            return None

    def partial_legs(row):
        """Scale-outs only: [(pct_of_position, price)] for Exit1 and Exit2."""
        out = []
        for i in (1, 2):
            px = _num(row.get("Exit%d_Price" % i))
            pc = _num(row.get("Exit%d_Pct" % i))
            if px and pc and pc > 0:
                out.append((pc, px))
        return out

    def exit_legs(row):
        """Every filled leg including the final exit, which takes whatever is left."""
        legs = partial_legs(row)
        taken = sum(w for w, _ in legs)
        final = _num(row.get("Exit_Price"))
        if final:
            legs = legs + [(max(0.0, 100.0 - taken), final)]
        return legs, taken

    def leg_return(entry, price, side):
        return ((price - entry) / entry * 100.0) if side == "Long" else ((entry - price) / entry * 100.0)

    def blended_result(row, live=None):
        """Weighted return across filled legs.

        With `live`, the position is still open: realised scale-outs are blended with
        the unsold remainder marked to the current price.
        """
        entry = _num(row.get("Entry"))
        if not entry:
            return None
        side = row.get("Side", "Long")
        if live is not None:
            legs = partial_legs(row)
            rem = max(0.0, 100.0 - sum(w for w, _ in legs))
            if rem > 0:
                legs = legs + [(rem, live)]
        else:
            legs, _ = exit_legs(row)
        legs = [(w, p) for w, p in legs if w > 0]
        if not legs:
            return None
        tot = sum(w for w, _ in legs)
        return sum(leg_return(entry, p, side) * (w / tot) for w, p in legs)

    def _avg_exit_txt(row):
        legs, _ = exit_legs(row)
        if not legs:
            return "—"
        tot = sum(w for w, _ in legs)
        avg = sum(p * w for w, p in legs) / tot if tot else legs[-1][1]
        return "{:,.2f}".format(avg)

    def _legs_txt(row):
        legs, _ = exit_legs(row)
        n = len([1 for w, _ in legs if w > 0])
        return "—" if n <= 1 else str(n)

    # ---- Closed trade results ----
    def closed_result(row):
        return blended_result(row)
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
                _b = blended_result(row, live=cur)
                pnl = _b if _b is not None else ((cur - entry) / entry * 100.0 if is_long else (entry - cur) / entry * 100.0)
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
            _taken = sum(w for w, _ in partial_legs(row))
            if _taken > 0:
                chips += ("<span style='border:1px solid " + AMBER + "; color:" + AMBER + "; font-size:10px; "
                          "padding:2px 8px; border-radius:4px; margin-left:6px;'>"
                          + "{:.0f}% taken".format(_taken) + "</span>")

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
                "<th style='text-align:right;'>Entry</th><th style='text-align:right;'>Exit</th><th style='text-align:center;'>Legs</th>"
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
                     "<td style='text-align:right;'>" + _avg_exit_txt(r) + "</td>"
                     "<td style='text-align:center;color:" + MUTED + ";'>" + _legs_txt(r) + "</td>"
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
    def grade_level(published_sup, bottom, top, d_open, d_high, d_low, d_close):
        """Grade one published zone against one session, by the role it actually had.

        SPX levels are published Sunday off Friday's cash close, so a Monday gap can
        invert a level before the cash open. A zone below the open acts as support and
        a zone above it acts as resistance, whatever it was labelled on Sunday. Grading
        by the effective role keeps the level in play instead of scoring a false break.

        Returns (grade, effective_sup, flipped).
        """
        if d_open >= top:
            eff = True          # price opened above the zone: it is support today
        elif d_open <= bottom:
            eff = False         # price opened below the zone: it is resistance today
        else:
            eff = published_sup  # opened inside the zone; keep the published role
        flipped = (eff != published_sup)

        if eff:
            if d_low > top:
                g = "none"
            elif d_close < bottom:
                g = "break"
            elif d_low < bottom and d_close >= bottom:
                g = "both"
            else:
                g = "hold"
        else:
            if d_high < bottom:
                g = "none"
            elif d_close > top:
                g = "break"
            elif d_high > top and d_close <= top:
                g = "both"
            else:
                g = "hold"
        return g, eff, flipped

    try:
        lv = pd.read_csv(SHEET_URL)
        lv = lv[lv["Ticker"].astype(str).str.strip() == A["sheet"]]
        if "Date" in lv.columns:
            lv["_dt"] = parse_date_col(lv["Date"]).dt.normalize()
    except Exception:
        lv = pd.DataFrame()

    card_html, tested, held = "", 0, 0
    ma_tested = ma_held = st_tested = st_held = flips = 0
    setups = []
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
        # Group by side AND label first: the 8MA and the 21MA are different levels
        # even when their ranges happen to overlap on different days of the week.
        groups = {}
        for x in raw:
            groups.setdefault((x["sup"], x["lbl"].strip().upper()), []).append(x)

        clusters = []
        for (side, _lblkey), grp in groups.items():
            items = sorted(grp, key=lambda x: (x["b"] + x["t"]) / 2.0)
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
                     "both": ("rgba(240,185,11,.30)", AMBER, "LBAF"), "none": ("#141a24", "#3d4757", "\u2014"),
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
                g, eff_sup, flipped = grade_level(c["sup"], zb, zt, float(d["Open"]), float(d["High"]),
                                                  float(d["Low"]), float(d["Close"]))
                cells.append((g, eff_sup, flipped))
                if g == "both":
                    # This is the look-below-and-fail / look-above-and-fail setup.
                    d_low, d_high, d_close = float(d["Low"]), float(d["High"]), float(d["Close"])
                    extreme = d_low if eff_sup else d_high
                    recovered = (d_close - d_low) if eff_sup else (d_high - d_close)
                    setups.append(dict(day=d.name, zone=(zb, zt), sup=eff_sup, lbl=lbl,
                                       extreme=extreme, close=d_close, pts=recovered,
                                       flipped=flipped))
                if g != "none":
                    any_test = True
                    tested += 1
                    if flipped:
                        flips += 1
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
            for cell in r["cells"]:
                if isinstance(cell, tuple):
                    g, eff_sup, flipped = cell
                else:
                    g, eff_sup, flipped = cell, r["sup"], False
                bgc, fgc, txt = style_map[g]
                if g == "hold":
                    txt = "HELD" if eff_sup else "REJ"
                elif g == "both":
                    txt = "LBAF" if eff_sup else "LAAF"
                if flipped and g in ("hold", "break", "both"):
                    txt += "*"
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
        worked = held + len(setups)
        tiles += tile("Levels Worked", "%d of %d" % (worked, tested),
                      "held, rejected, or swept and reclaimed",
                      GREEN if worked >= tested * 0.6 else AMBER)
        if setups:
            tiles += tile("Setups Fired", str(len(setups)),
                          "look below / above and fail", AMBER)
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
                    "<strong style='color:" + AMBER + ";'>LBAF</strong> = look below and fail, price swept the support and closed back above · "
                    "<strong style='color:" + AMBER + ";'>LAAF</strong> = look above and fail, price poked the resistance and closed back below · "
                    "HELD = support held on the test · REJ = resistance turned it away · BRK = closed through · — = price never reached it. "
                    "Graded by the role the level actually had at the open; an asterisk means a gap flipped it from the side it was published on.</p>",
                    unsafe_allow_html=True)
        st.markdown("<div class='ns-panel'>" + card_html + "</div>", unsafe_allow_html=True)
        if setups:
            setups.sort(key=lambda s: -s["pts"])
            rows_html = ""
            for s in setups:
                kind = "Look below and fail" if s["sup"] else "Look above and fail"
                zb, zt = s["zone"]
                zone_txt = "{:,.0f}".format(zb) if abs(zt - zb) < 0.5 else "{:,.0f} – {:,.0f}".format(zb, zt)
                if s["lbl"]:
                    zone_txt += " (" + s["lbl"] + ")"
                rows_html += ("<tr><td style='color:" + MUTED + ";'>" + s["day"].strftime("%a") + "</td>"
                              "<td style='font-weight:600;color:" + (GREEN if s["sup"] else RED) + ";'>" + kind + "</td>"
                              "<td>" + zone_txt + ("*" if s["flipped"] else "") + "</td>"
                              "<td style='text-align:right;'>" + "{:,.0f}".format(s["extreme"]) + "</td>"
                              "<td style='text-align:right;'>" + "{:,.0f}".format(s["close"]) + "</td>"
                              "<td style='text-align:right;font-weight:700;color:" + AMBER + ";'>"
                              + "{:+,.0f}".format(s["pts"]) + "</td></tr>")
            best = setups[0]
            st.markdown("<div class='ns-section' style='margin-top:18px;'>🎯 Setups That Fired</div>",
                        unsafe_allow_html=True)
            st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                        "Every look-below-and-fail and look-above-and-fail at a published level this week, "
                        "with the points from the sweep back to the close.</p>", unsafe_allow_html=True)
            st.markdown("<table class='ns-tbl'><tr>"
                        "<th style='text-align:left;'>Day</th><th style='text-align:left;'>Setup</th>"
                        "<th style='text-align:left;'>Level</th><th style='text-align:right;'>Swept to</th>"
                        "<th style='text-align:right;'>Close</th><th style='text-align:right;'>Points</th>"
                        "</tr>" + rows_html + "</table>", unsafe_allow_html=True)
            st.markdown("<div class='ns-panel' style='margin-top:8px; border-left:3px solid " + AMBER + ";'>"
                        "<span style='font-size:13.5px; color:#cdd8e4;'><strong>"
                        + str(len(setups)) + " setup" + ("" if len(setups) == 1 else "s")
                        + " fired at published levels this week.</strong> The best was "
                        + ("the look below and fail at " if best["sup"] else "the look above and fail at ")
                        + ("{:,.0f}".format(best["zone"][0]) if abs(best["zone"][1] - best["zone"][0]) < 0.5
                           else "{:,.0f} – {:,.0f}".format(best["zone"][0], best["zone"][1]))
                        + " on " + best["day"].strftime("%A") + ", worth " + "{:,.0f}".format(best["pts"])
                        + " points from the sweep to the close.</span></div>", unsafe_allow_html=True)

        if flips:
            st.markdown("<div class='ns-panel' style='margin-top:8px; border-left:3px solid " + AMBER + ";'>"
                        "<span style='font-size:13.5px; color:#cdd8e4;'><strong>" + str(flips) + " level "
                        + ("test" if flips == 1 else "tests") + " came from the opposite side.</strong> "
                        "SPX levels are set before the cash open, so a gap can turn a published support into "
                        "resistance (or the reverse) before the bell. Those are marked with an asterisk, and they "
                        "still count: the price mattered, just from the other direction.</span></div>",
                        unsafe_allow_html=True)
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
    st.markdown("<div class='ns-section'>🏆 Biggest Movers On The Week</div>", unsafe_allow_html=True)
    st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                "Ranked by size of move, Monday\u2019s open to the latest print. The board reshuffles as the week goes on.</p>", unsafe_allow_html=True)
    mv = get_week_change(WATCHLIST, s_str, e_str)

    @st.cache_data(ttl=1800)
    def get_hist_closes(tickers, end_str):
        start = (pd.Timestamp(end_str) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
        return fetch_many_closes(list(tickers), start, end_str)

    hist = get_hist_closes(tuple(WATCHLIST), e_str)

    def trend_character(tkr):
        """Where a name sits against its own moving averages, and how stretched it is.

        A weekly percentage says nothing about whether a name is a good entry. The
        labels below are directional: a name in a clean downtrend is a different
        proposition from one that has already fallen 15% below its 21MA, just as a
        continuation long differs from a name that is badly extended. Returns
        (label, colour, extension %) or None.
        """
        if hist is None or tkr not in hist.columns:
            return None
        s = hist[tkr].dropna()
        if len(s) < 60:
            return None
        e8 = s.ewm(span=8, adjust=False).mean()
        e21 = s.ewm(span=21, adjust=False).mean()
        s50 = s.rolling(50).mean()
        px = float(s.iloc[-1])
        ext = (px / float(e21.iloc[-1]) - 1.0) * 100.0

        above8 = px > float(e8.iloc[-1])
        above21 = px > float(e21.iloc[-1])
        above50 = pd.notna(s50.iloc[-1]) and px > float(s50.iloc[-1])
        was_below21 = bool((s.iloc[-6:-1] < e21.iloc[-6:-1]).any())
        was_above21 = bool((s.iloc[-6:-1] > e21.iloc[-6:-1]).any())

        # ---- uptrend: above all three ----
        if above8 and above21 and above50:
            if was_below21:
                return ("Reclaim", BLUE, ext)
            if ext >= 12.0:
                return ("Very extended", RED, ext)
            if ext >= 8.0:
                return ("Extended", AMBER, ext)
            return ("Continuation", GREEN, ext)

        # ---- downtrend: below all three ----
        if (not above8) and (not above21) and (not above50):
            if was_above21:
                return ("Fresh breakdown", RED, ext)
            if ext <= -12.0:
                return ("Very extended down", BLUE, ext)
            if ext <= -8.0:
                return ("Extended down", AMBER, ext)
            return ("Downtrend", RED, ext)

        # ---- in between ----
        if (not above50) and above21:
            return ("Bouncing", AMBER, ext)      # counter-trend rally inside a downtrend
        if above50 and not above21:
            return ("Losing the 21MA", AMBER, ext)
        return ("Mixed", MUTED, ext)
    if mv:
        ranked = sorted(mv.items(), key=lambda kv: -kv[1])
        leaders, laggards = ranked[:6], ranked[-6:][::-1]

        def mover_panel(title, items, color):
            h = ("<div class='ns-panel'><div style='font-size:11.5px;text-transform:uppercase;letter-spacing:0.8px;color:"
                 + MUTED + ";font-weight:600;margin-bottom:10px;'>" + title + "</div>")
            for tk, v in items:
                ch = trend_character(tk)
                chip = ""
                if ch is not None:
                    lab, ccol, ext = ch
                    chip = ("<span style='border:1px solid " + ccol + ";color:" + ccol + ";font-size:10.5px;"
                            "font-weight:600;padding:1px 7px;border-radius:4px;margin-left:10px;'>" + lab + "</span>"
                            "<span style='color:" + MUTED + ";font-family:IBM Plex Mono,monospace;font-size:11.5px;"
                            "margin-left:8px;'>" + "{:+.1f}% vs 21MA".format(ext) + "</span>")
                h += ("<div style='display:flex;align-items:center;background:" + PANEL2 + ";border:1px solid " + LINE
                      + ";border-radius:6px;padding:9px 13px;margin-bottom:6px;'>"
                      "<span style='font-family:Space Grotesk,sans-serif;font-weight:700;font-size:14px;'>" + tk + "</span>"
                      + chip +
                      "<span style='margin-left:auto;font-family:IBM Plex Mono,monospace;font-size:14px;font-weight:600;color:"
                      + (GREEN if v >= 0 else RED) + ";'>" + "{:+.1f}%".format(v) + "</span></div>")
            return h + "</div>"

        mc1, mc2 = st.columns(2)
        with mc1:
            st.markdown(mover_panel("Leaders", leaders, GREEN), unsafe_allow_html=True)
        with mc2:
            st.markdown(mover_panel("Laggards", laggards, RED), unsafe_allow_html=True)

    # ---------- 6. Day-by-day consistency ----------
    st.markdown("<div class='ns-section'>📆 Most Consistent, Day By Day</div>", unsafe_allow_html=True)
    st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                "Ranked by how many sessions a name finished in the top or bottom five, not by the size of its move. "
                "A steady name can rank here without making the movers board above, and a one-day spike can do the reverse. "
                "Week figures match that board.</p>",
                unsafe_allow_html=True)

    @st.cache_data(ttl=1800)
    def get_week_closes(tickers, start_str, end_str):
        return fetch_many_closes(list(tickers), start_str, end_str)

    # Reach back a week so the first session has a prior close to measure against
    closes = get_week_closes(tuple(WATCHLIST),
                             (week_start - pd.Timedelta(days=7)).strftime("%Y-%m-%d"), e_str)

    if closes is None or closes.empty:
        st.info("Daily data for the watchlist isn't available right now.")
    else:
        pct_all = closes.pct_change() * 100.0
        in_week = [i for i, d in enumerate(pct_all.index)
                   if week_start.date() <= d.date() <= week_end.date()]
        pct = pct_all.iloc[in_week].dropna(how="all") if in_week else pct_all.iloc[0:0]

        if len(pct) == 0:
            st.info("No completed sessions in the selected week yet.")
        else:
            # The movers board above measures Monday's OPEN to Friday's close. Daily
            # close-to-close changes would instead carry in the weekend gap, which made
            # the two tables disagree on the same stock's week. Take the week figure from
            # the same source the movers board uses, then restate Monday's cell as
            # open-to-close so the row compounds back to exactly that number.
            wk_chg = mv if mv else {}
            for t in list(pct.columns):
                w = wk_chg.get(t)
                if w is None:
                    continue
                rest = 1.0
                for d in pct.index[1:]:
                    v = pct.loc[d, t]
                    if pd.notna(v):
                        rest *= (1 + v / 100.0)
                if rest:
                    pct.loc[pct.index[0], t] = ((1 + w / 100.0) / rest - 1) * 100.0
            cum = pd.Series({t: wk_chg.get(t, float("nan")) for t in pct.columns})
            pct = pct[[t for t in pct.columns if pd.notna(cum[t])]]
            cum = cum.dropna()
            if pct.empty:
                st.info("Weekly figures for the watchlist aren't available right now.")
                st.stop()

            TOPN = 5
            led = {t: 0 for t in pct.columns}
            lag = {t: 0 for t in pct.columns}
            for _, row in pct.iterrows():
                r = row.dropna().sort_values(ascending=False)
                if len(r) < TOPN * 2:
                    continue
                for t in r.index[:TOPN]:
                    led[t] += 1
                for t in r.index[-TOPN:]:
                    lag[t] += 1
            n_sessions = len(pct)
            day_names = [d.strftime("%a") for d in pct.index]
            mx = max(pct.abs().max().max(), 0.1)

            def consistency_panel(title, tally, ascending, accent):
                names = [t for t, c in tally.items() if c > 0]
                names.sort(key=lambda t: (-tally[t], cum[t] if ascending else -cum[t]))
                names = names[:6]
                if not names:
                    return ""
                head = ("<tr><th style='text-align:left;width:74px;'>" + title + "</th>")
                for dn in day_names:
                    head += "<th>" + dn + "</th>"
                head += "<th style='text-align:right;'>Week</th><th style='text-align:right;'>Days</th></tr>"
                body = ""
                for t in names:
                    row = "<td class='tk'>" + t + "</td>"
                    for d in pct.index:
                        v = pct.loc[d, t]
                        if pd.isna(v):
                            bgc, fgc, txt = "#141a24", "#3d4757", "\u2014"
                        else:
                            inten = min(0.55, 0.10 + abs(v) / mx * 0.45)
                            bgc = ("rgba(38,166,154,%.2f)" % inten) if v >= 0 else ("rgba(239,83,80,%.2f)" % inten)
                            fgc = GREEN if v >= 0 else RED
                            txt = "{:+.1f}".format(v)
                        row += ("<td><span style='display:block;height:28px;line-height:28px;border-radius:5px;background:"
                                + bgc + ";color:" + fgc + ";font-family:IBM Plex Mono,monospace;font-size:13px;"
                                "font-weight:600;'>" + txt + "</span></td>")
                    wk = float(cum[t])
                    streak = tally[t] == n_sessions and n_sessions > 1
                    row += ("<td style='text-align:right;font-family:IBM Plex Mono,monospace;font-size:14px;"
                            "font-weight:600;color:" + (GREEN if wk >= 0 else RED) + ";'>" + "{:+.1f}%".format(wk) + "</td>")
                    row += ("<td style='text-align:right;font-family:IBM Plex Mono,monospace;font-size:13px;color:"
                            + (AMBER if streak else MUTED) + ";font-weight:" + ("700" if streak else "500") + ";'>"
                            + str(tally[t]) + "/" + str(n_sessions) + ("  \u2605" if streak else "") + "</td>")
                    body += "<tr>" + row + "</tr>"
                return ("<table class='cs'>" + head + body + "</table>")

            css = ("<style>.cs{width:100%;border-collapse:collapse;margin-bottom:6px}"
                   ".cs th{font-size:11.5px;text-transform:uppercase;letter-spacing:0.7px;color:" + MUTED
                   + ";padding:0 4px 9px;font-weight:600;text-align:center}"
                   ".cs td{padding:4px 3px;text-align:center}"
                   ".cs td.tk{text-align:left;font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:15px;color:"
                   + TEXT + "}</style>")

            lead_tbl = consistency_panel("Leaders", led, False, GREEN)
            lag_tbl = consistency_panel("Laggards", lag, True, RED)
            st.markdown("<div class='ns-panel'>" + css + lead_tbl + "</div>", unsafe_allow_html=True)
            st.markdown("<div class='ns-panel'>" + css + lag_tbl + "</div>", unsafe_allow_html=True)

            # Call out anything that never left the top or bottom five
            perfect_up = [t for t, c in led.items() if c == n_sessions and n_sessions > 1]
            perfect_dn = [t for t, c in lag.items() if c == n_sessions and n_sessions > 1]
            if perfect_up or perfect_dn:
                bits = []
                if perfect_up:
                    bits.append("<strong style='color:" + GREEN + ";'>" + ", ".join(sorted(perfect_up))
                                + "</strong> finished in the top five every session")
                if perfect_dn:
                    bits.append("<strong style='color:" + RED + ";'>" + ", ".join(sorted(perfect_dn))
                                + "</strong> finished in the bottom five every session")
                st.markdown("<div class='ns-panel' style='border-left:3px solid " + AMBER + ";'>"
                            "<span style='font-size:13.5px;color:#cdd8e4;'>Persistent all week: "
                            + "; ".join(bits) + ". That is trend, not noise.</span></div>", unsafe_allow_html=True)

    # ---------- 7. Did last week's movers follow through? ----------
    st.markdown("<div class='ns-section'>🔁 Did Last Week's Movers Follow Through?</div>", unsafe_allow_html=True)
    st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                "Last week's biggest movers, and what they actually did this week. "
                "A leaders board only means something if strength carries.</p>", unsafe_allow_html=True)

    pw_start = week_start - pd.Timedelta(weeks=1)
    pw_end = week_end - pd.Timedelta(weeks=1)
    pw_chg = get_week_change(WATCHLIST, pw_start.strftime("%Y-%m-%d"),
                             (pw_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))

    if not pw_chg or not mv:
        st.info("Not enough history to compare the two weeks yet.")
    else:
        pw_rank = sorted(pw_chg.items(), key=lambda kv: -kv[1])
        prior_lead = [t for t, _ in pw_rank[:6] if t in mv]
        prior_lag = [t for t, _ in pw_rank[-6:][::-1] if t in mv]

        def follow_table(title, names, was_up):
            if not names:
                return ""
            rows = ""
            for t in names:
                last, now = pw_chg[t], mv[t]
                carried = (now > 0) if was_up else (now < 0)
                if abs(now) < 0.5:
                    verdict, vcol = "Stalled", MUTED
                elif carried:
                    verdict, vcol = "Continued", GREEN
                else:
                    verdict, vcol = "Reversed", RED
                rows += ("<tr><td style='font-weight:700;'>" + t + "</td>"
                         "<td style='text-align:right;color:" + MUTED + ";'>" + "{:+.1f}%".format(last) + "</td>"
                         "<td style='text-align:right;font-weight:600;color:" + (GREEN if now >= 0 else RED) + ";'>"
                         + "{:+.1f}%".format(now) + "</td>"
                         "<td style='text-align:right;color:" + vcol + ";font-weight:600;'>" + verdict + "</td></tr>")
            return ("<div style='font-size:11.5px;text-transform:uppercase;letter-spacing:0.8px;color:" + MUTED
                    + ";font-weight:600;margin:0 0 8px 2px;'>" + title + "</div>"
                    "<table class='ns-tbl'><tr><th style='text-align:left;'>Ticker</th>"
                    "<th style='text-align:right;'>Last wk</th><th style='text-align:right;'>This wk</th>"
                    "<th style='text-align:right;'>Result</th></tr>" + rows + "</table>")

        fc1, fc2 = st.columns(2)
        with fc1:
            st.markdown(follow_table("Last week's leaders", prior_lead, True), unsafe_allow_html=True)
        with fc2:
            st.markdown(follow_table("Last week's laggards", prior_lag, False), unsafe_allow_html=True)

        # The one number that answers "is chasing strength working right now?"
        if prior_lead:
            avg_lead = sum(mv[t] for t in prior_lead) / len(prior_lead)
            kept = sum(1 for t in prior_lead if mv[t] > 0)
            edge = avg_lead - wk_pct
            st.markdown("<div class='ns-panel' style='margin-top:10px;border-left:3px solid "
                        + (GREEN if edge >= 0 else RED) + ";'>"
                        "<span style='font-size:13.5px;color:#cdd8e4;'><strong>Buying last week's six leaders "
                        "returned " + "{:+.1f}%".format(avg_lead) + " on average this week</strong> against "
                        + "{:+.1f}%".format(wk_pct) + " for the index, so chasing strength was worth "
                        + "{:+.1f}%".format(edge) + " this week. " + str(kept) + " of " + str(len(prior_lead))
                        + " kept going. One week is not a pattern; the value is in watching this number "
                        "week after week.</span></div>", unsafe_allow_html=True)

    st.markdown("<p style='color:" + MUTED + "; font-size:11.5px; text-align:center; margin-top:16px;'>"
                "This is not trading advice. This is purely for information/education.</p>", unsafe_allow_html=True)


# ==========================================
# PAGE 4: SWING SCREENER
# ==========================================
elif page_selection == "Swing Screener":

    st.title("Next Step Trading: Swing Candidates")
    st.markdown("<p style='color:" + MUTED + "; font-size:15px;'>The daily-chart version of the intraday method: "
                "a pullback into the 21MA inside an established trend, a look below and fail, a structural stop, "
                "and targets at real levels. Nothing is listed unless the reward pays for the risk.</p>",
                unsafe_allow_html=True)

    UNIVERSE_SECTORS = {
        # semis
        "NVDA":"Semiconductors","AVGO":"Semiconductors","AMD":"Semiconductors","QCOM":"Semiconductors",
        "TXN":"Semiconductors","AMAT":"Semiconductors","MU":"Semiconductors","LRCX":"Semiconductors",
        "KLAC":"Semiconductors","ADI":"Semiconductors","MRVL":"Semiconductors","NXPI":"Semiconductors",
        "ON":"Semiconductors","MCHP":"Semiconductors","INTC":"Semiconductors","SWKS":"Semiconductors",
        "QRVO":"Semiconductors","TER":"Semiconductors","SMCI":"Semiconductors",
        # software
        "MSFT":"Software","ADBE":"Software","CRM":"Software","ORCL":"Software","NOW":"Software",
        "PANW":"Software","CRWD":"Software","ZS":"Software","DDOG":"Software","NET":"Software",
        "MDB":"Software","TEAM":"Software","WDAY":"Software","INTU":"Software","ADSK":"Software",
        "ANSS":"Software","SNPS":"Software","CDNS":"Software","SNOW":"Software","PLTR":"Software",
        # hardware / IT services
        "AAPL":"Tech Hardware","CSCO":"Tech Hardware","IBM":"Tech Hardware","ACN":"Tech Hardware",
        "INFY":"Tech Hardware","HPQ":"Tech Hardware","DELL":"Tech Hardware","WDC":"Tech Hardware",
        "STX":"Tech Hardware","APH":"Tech Hardware","GLW":"Tech Hardware","KEYS":"Tech Hardware",
        # internet / media
        "GOOGL":"Internet & Media","META":"Internet & Media","NFLX":"Internet & Media","DIS":"Internet & Media",
        "CMCSA":"Internet & Media","CHTR":"Internet & Media","WBD":"Internet & Media","PARA":"Internet & Media",
        "EA":"Internet & Media","TTWO":"Internet & Media","RBLX":"Internet & Media","SPOT":"Internet & Media",
        "UBER":"Internet & Media","LYFT":"Internet & Media","DASH":"Internet & Media","ABNB":"Internet & Media",
        "BKNG":"Internet & Media",
        "T":"Telecom","VZ":"Telecom","TMUS":"Telecom",
        # financials
        "JPM":"Banks","BAC":"Banks","WFC":"Banks","C":"Banks","USB":"Banks","PNC":"Banks","TFC":"Banks",
        "COF":"Banks","DFS":"Banks","SYF":"Banks",
        "GS":"Capital Markets","MS":"Capital Markets","SCHW":"Capital Markets","BLK":"Capital Markets",
        "BX":"Capital Markets","KKR":"Capital Markets","APO":"Capital Markets","TROW":"Capital Markets",
        "BEN":"Capital Markets","AMP":"Capital Markets","ICE":"Capital Markets","CME":"Capital Markets",
        "NDAQ":"Capital Markets","MSCI":"Capital Markets","SPGI":"Capital Markets","MCO":"Capital Markets",
        "V":"Payments","MA":"Payments","AXP":"Payments","PYPL":"Payments","FI":"Payments",
        # healthcare
        "JNJ":"Pharma","LLY":"Pharma","PFE":"Pharma","MRK":"Pharma","ABBV":"Pharma","BMY":"Pharma","ZTS":"Pharma",
        "AMGN":"Biotech","GILD":"Biotech","BIIB":"Biotech","VRTX":"Biotech","REGN":"Biotech","MRNA":"Biotech",
        "TMO":"Medical Devices","DHR":"Medical Devices","ABT":"Medical Devices","SYK":"Medical Devices",
        "BSX":"Medical Devices","MDT":"Medical Devices","EW":"Medical Devices","ISRG":"Medical Devices",
        "BDX":"Medical Devices",
        "UNH":"Healthcare Services","HCA":"Healthcare Services","CI":"Healthcare Services","CVS":"Healthcare Services",
        "ELV":"Healthcare Services","MCK":"Healthcare Services","COR":"Healthcare Services",
        # energy, split so refiners cannot stack
        "VLO":"Refiners","MPC":"Refiners","PSX":"Refiners","DINO":"Refiners",
        "XOM":"Oil & Gas","CVX":"Oil & Gas","COP":"Oil & Gas","EOG":"Oil & Gas","OXY":"Oil & Gas",
        "DVN":"Oil & Gas","FANG":"Oil & Gas","HES":"Oil & Gas","APA":"Oil & Gas","MRO":"Oil & Gas",
        "CTRA":"Oil & Gas","EQT":"Oil & Gas",
        "SLB":"Oil Services","HAL":"Oil Services","BKR":"Oil Services",
        "KMI":"Midstream","WMB":"Midstream","OKE":"Midstream","TRGP":"Midstream","LNG":"Midstream",
        # industrials
        "CAT":"Industrials","DE":"Industrials","HON":"Industrials","MMM":"Industrials","EMR":"Industrials",
        "ETN":"Industrials","PH":"Industrials","ITW":"Industrials","CMI":"Industrials","PCAR":"Industrials",
        "URI":"Industrials","FAST":"Industrials","GWW":"Industrials","ROK":"Industrials","DOV":"Industrials",
        "GE":"Industrials",
        "BA":"Aerospace & Defense","LMT":"Aerospace & Defense","RTX":"Aerospace & Defense",
        "NOC":"Aerospace & Defense","GD":"Aerospace & Defense",
        "UNP":"Transports","CSX":"Transports","NSC":"Transports","UPS":"Transports","FDX":"Transports",
        "DAL":"Transports","UAL":"Transports","LUV":"Transports",
        "WM":"Waste","RSG":"Waste",
        # consumer
        "WMT":"Retail","COST":"Retail","TGT":"Retail","HD":"Retail","LOW":"Retail","DG":"Retail",
        "DLTR":"Retail","KR":"Retail","TJX":"Retail","ROST":"Retail","ORLY":"Retail","AZO":"Retail",
        "NKE":"Retail","LULU":"Retail",
        "PG":"Staples","KO":"Staples","PEP":"Staples","PM":"Staples","MO":"Staples","MDLZ":"Staples",
        "KHC":"Staples","GIS":"Staples","K":"Staples","HSY":"Staples","STZ":"Staples","KDP":"Staples",
        "MNST":"Staples","CL":"Staples","KMB":"Staples","EL":"Staples","CHD":"Staples","CLX":"Staples",
        "SYY":"Staples",
        "MCD":"Restaurants & Travel","SBUX":"Restaurants & Travel","CMG":"Restaurants & Travel",
        "YUM":"Restaurants & Travel","DRI":"Restaurants & Travel","MAR":"Restaurants & Travel",
        "HLT":"Restaurants & Travel","LVS":"Restaurants & Travel","MGM":"Restaurants & Travel",
        "RCL":"Restaurants & Travel","CCL":"Restaurants & Travel","NCLH":"Restaurants & Travel",
        "GM":"Autos & Housing","F":"Autos & Housing","APTV":"Autos & Housing","LEN":"Autos & Housing",
        "DHI":"Autos & Housing","PHM":"Autos & Housing","NVR":"Autos & Housing",
        "AMZN":"Consumer Discretionary","TSLA":"Consumer Discretionary",
        # materials, utilities, real estate
        "LIN":"Materials","APD":"Materials","SHW":"Materials","ECL":"Materials","FCX":"Materials",
        "NEM":"Materials","NUE":"Materials","STLD":"Materials","VMC":"Materials","MLM":"Materials",
        "DOW":"Chemicals","DD":"Chemicals","PPG":"Chemicals","ALB":"Chemicals","CF":"Chemicals","MOS":"Chemicals",
        "NEE":"Utilities","DUK":"Utilities","SO":"Utilities","D":"Utilities","AEP":"Utilities","EXC":"Utilities",
        "SRE":"Utilities","XEL":"Utilities","ED":"Utilities","PEG":"Utilities","WEC":"Utilities","ES":"Utilities",
        "PCG":"Utilities","VST":"Utilities","CEG":"Utilities",
        "AMT":"REITs","PLD":"REITs","CCI":"REITs","EQIX":"REITs","PSA":"REITs","SPG":"REITs","O":"REITs",
        "WELL":"REITs","DLR":"REITs","VICI":"REITs","AVB":"REITs","EQR":"REITs",
    }
    UNIVERSE = sorted(UNIVERSE_SECTORS.keys())

    # ── Operator controls are hidden unless the passcode matches ──
    try:
        _code = st.secrets.get("SCREENER_PASSCODE", None)
    except Exception:
        _code = None
    if _code:
        _entered = st.sidebar.text_input("Operator passcode", type="password", key="scr_pass")
        operator = (_entered == _code)
    else:
        operator = False
        st.sidebar.caption("Screener controls are locked. Add SCREENER_PASSCODE to the app secrets to unlock them.")

    # Defaults that the public view always uses
    direction, risk_pct, min_rr, max_ext, min_dv, req_rs = "Long", 1.5, 2.0, 6.0, 20.0, True
    pos_cap, max_atr, pullback_win = 15.0, 15.0, 5
    min_stop_atr = 0.75
    scale_plan = "50 / 25 / 25"

    if operator:
        c1, c2, c3 = st.columns(3)
        with c1:
            direction = st.radio("Setups", ["Long", "Short"], horizontal=True)
            risk_pct = st.number_input("Risk per trade (% of book)", 0.25, 5.0, 1.5, 0.25)
        with c2:
            min_rr = st.number_input("Minimum R:R to T1", 1.0, 5.0, 2.0, 0.25)
            max_ext = st.number_input("Max distance from 21MA (%)", 2.0, 20.0, 6.0, 0.5)
        with c3:
            min_dv = st.number_input("Min average dollar volume ($M)", 1.0, 500.0, 20.0, 5.0)
            req_rs = st.checkbox("Require relative strength vs SPX (3 months)", value=True)
        c4, c5 = st.columns(2)
        with c4:
            pos_cap = st.number_input("Max position size (% of book)", 5.0, 50.0, 15.0, 2.5,
                                      help="A tight stop can justify an enormous position on paper. It cannot protect against a gap.")
        with c5:
            st.caption("Sector concentration is flagged on each row rather than filtered, so nothing "
                       "qualifying is hidden. The call is yours at the chart.")
        pullback_win = st.number_input("Setup must have fired within (sessions)", 3, 15, 5, 1,
                                       help="How recently price dipped through the 21MA. Widen it to keep setups "
                                            "on the list longer instead of ageing out after a week.")
        scale_plan = st.selectbox("Scale-out plan", ["50 / 25 / 25", "All out at T1", "Thirds", "50 / 50 at T2"],
                                  index=0,
                                  help="Share of the position taken at T1, T2 and T3. The stop moves to breakeven "
                                       "once T1 fills, which the modelling showed is worth more than the ratio itself.")
        min_stop_atr = st.number_input("Minimum stop distance (ATRs)", 0.25, 3.0, 0.75, 0.05,
                                      help="A stop closer than this gets hit by ordinary noise regardless of whether "
                                           "the setup is right, and it inflates R:R. Setups whose swing low sits "
                                           "nearer than this are rejected rather than widened, because a widened stop "
                                           "is no longer the structural level.")
        max_atr = st.number_input("Max average daily ranges to T1", 4.0, 60.0, 15.0, 1.0,
                                  help="One ATR is roughly one session of movement, so 15 is about three weeks. "
                                       "A structurally valid target that sits 40 ATRs away is a position trade, not a swing.")
    else:
        st.caption("Candidates are generated from a fixed rule set: 21MA pullback in an established uptrend, "
                   "structural stop, minimum 2:1 reward to the first target, and a target reachable inside a swing timeframe.")

    @st.cache_data(ttl=3600, show_spinner="Scanning the universe...")
    def get_universe_ohlc(tickers, end_str):
        start = (pd.Timestamp(end_str) - pd.Timedelta(days=420)).strftime("%Y-%m-%d")
        out = {}
        tl = list(tickers)
        for i in range(0, len(tl), 120):
            chunk = tl[i:i + 120]
            try:
                data = _fetch_with_retry(lambda c=chunk: yf.download(
                    tickers=" ".join(c), start=start, end=end_str, interval="1d",
                    group_by="ticker", auto_adjust=True, progress=False, threads=False))
            except Exception:
                continue
            if data is None or len(data) == 0:
                continue
            for t in chunk:
                try:
                    df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
                    df = df.dropna(subset=["Close"])
                    if len(df) > 120:
                        out[t] = df
                except Exception:
                    continue
        return out

    @st.cache_data(ttl=300)
    def get_open_book(url):
        """Tickers already held, so a repeat candidate is not mistaken for a new idea."""
        try:
            b = pd.read_csv(url).dropna(subset=["Ticker"])
        except Exception:
            return {}
        b["Ticker"] = b["Ticker"].astype(str).str.strip().str.upper()
        b["Status"] = b["Status"].astype(str).str.strip().str.upper()
        out = {}
        for _, r in b[b["Status"] == "OPEN"].iterrows():
            try:
                out[r["Ticker"]] = dict(entry=float(r["Entry"]),
                                        sector=str(r.get("Sector", "") or "").strip(),
                                        opened=str(r.get("Date_Opened", "") or "").strip())
            except Exception:
                continue
        return out

    open_book = get_open_book(SWING_SHEET_URL)

    end_str = (pd.Timestamp.now().normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    data = get_universe_ohlc(tuple(UNIVERSE), end_str)
    if not data:
        st.warning("Market data could not be loaded right now. Wait a moment and reload.")
        st.stop()

    # While the cash session is open, today's daily bar is unfinished: its close is
    # just the current price, so entries, stops, R:R and ATR would all drift through
    # the day. Drop it and work from the last completed session instead, which keeps
    # this list identical from one close to the next.
    try:
        now_et = pd.Timestamp.now(tz="US/Eastern")
    except Exception:
        now_et = pd.Timestamp.now()
    session_live = (now_et.weekday() < 5) and (9 <= now_et.hour < 16)
    today_d = now_et.normalize().date()
    if session_live:
        trimmed = {}
        for t, df in data.items():
            if len(df) and df.index[-1].date() == today_d:
                df = df.iloc[:-1]
            if len(df) > 120:
                trimmed[t] = df
        data = trimmed
    asof = None
    for df in data.values():
        d = df.index[-1].date()
        asof = d if asof is None or d > asof else asof

    spx_3m = None
    try:
        sx = fetch_history("^SPX", period="6mo", interval="1d")
        if sx is not None and len(sx) > 65:
            spx_3m = (float(sx["Close"].iloc[-1]) / float(sx["Close"].iloc[-64]) - 1.0) * 100.0
    except Exception:
        pass

    def pivots(series, lr=5, want_high=True):
        w = lr * 2 + 1
        roll = series.rolling(w, center=True).max() if want_high else series.rolling(w, center=True).min()
        return series[(series == roll)].dropna()

    def scan(t, df, want_long):
        c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
        px = float(c.iloc[-1])
        e21 = c.ewm(span=21, adjust=False).mean()
        s50 = c.rolling(50).mean()
        if pd.isna(s50.iloc[-1]):
            return None
        # Average true range: one ATR is roughly one session of movement, so the
        # distance to a target in ATRs is an estimate of how long it would take.
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        atr = float(tr.tail(14).mean())
        if not atr or pd.isna(atr) or atr <= 0:
            return None
        m21, m50 = float(e21.iloc[-1]), float(s50.iloc[-1])
        ext = (px / m21 - 1.0) * 100.0
        dv = float((c * v).tail(20).mean()) / 1e6
        if dv < min_dv:
            return None
        rs = (px / float(c.iloc[-64]) - 1.0) * 100.0 if len(c) > 64 else None

        if want_long:
            if not (px > m21 > m50 and px > m50):
                return None
            if ext > max_ext:
                return None
            if not bool((df["Low"].iloc[-int(pullback_win):] < e21.iloc[-int(pullback_win):]).any()):
                return None
            if req_rs and (rs is None or spx_3m is None or rs <= spx_3m):
                return None
            stop = float(l.tail(10).min()) * 0.995
            if stop >= px:
                return None
            risk = px - stop
            if risk < atr * min_stop_atr:
                return None
            tg = sorted([float(x) for x in pivots(h.tail(160), 5, True).values if x > px * 1.005])[:3]
            if len(tg) < 3:
                lo60, hi60 = float(l.tail(60).min()), float(h.tail(60).max())
                rng = max(hi60 - lo60, px * 0.02)
                tg += [lo60 + rng * m for m in (1.272, 1.618, 2.0) if lo60 + rng * m > px * 1.005]
                tg = sorted(set(round(x, 2) for x in tg))[:3]
            if not tg:
                return None
            rr = (tg[0] - px) / risk
        else:
            if not (px < m21 < m50 and px < m50):
                return None
            if abs(ext) > max_ext:
                return None
            if not bool((df["High"].iloc[-int(pullback_win):] > e21.iloc[-int(pullback_win):]).any()):
                return None
            if req_rs and (rs is None or spx_3m is None or rs >= spx_3m):
                return None
            stop = float(h.tail(10).max()) * 1.005
            if stop <= px:
                return None
            risk = stop - px
            if risk < atr * min_stop_atr:
                return None
            tg = sorted([float(x) for x in pivots(l.tail(160), 5, False).values if x < px * 0.995], reverse=True)[:3]
            if len(tg) < 3:
                lo60, hi60 = float(l.tail(60).min()), float(h.tail(60).max())
                rng = max(hi60 - lo60, px * 0.02)
                tg += [hi60 - rng * m for m in (1.272, 1.618, 2.0) if 0 < hi60 - rng * m < px * 0.995]
                tg = sorted(set(round(x, 2) for x in tg), reverse=True)[:3]
            if not tg:
                return None
            rr = (px - tg[0]) / risk

        if rr < min_rr:
            return None
        atr_t1 = abs(tg[0] - px) / atr
        if atr_t1 > max_atr:
            return None
        raw_size = risk_pct / (risk / px * 100.0) * 100.0
        return dict(t=t, sec=UNIVERSE_SECTORS.get(t, "Other"), px=px, stop=stop, tg=tg, rr=rr,
                    ext=ext, rs=rs, atr=atr, atr_t1=atr_t1, stop_atr=risk / atr, raw=raw_size,
                    size=min(raw_size, pos_cap), capped=raw_size > pos_cap)

    want_long = (direction == "Long")
    hits = []
    for t, df in data.items():
        try:
            r = scan(t, df, want_long)
            if r:
                hits.append(r)
        except Exception:
            continue
    for r in hits:
        held = open_book.get(r["t"])
        r["held"] = held is not None
        r["book_entry"] = held["entry"] if held else None
    # new ideas first, then held names, each by R:R
    hits.sort(key=lambda r: (r["held"], -r["rr"]))

    # Concentration control: best R:R per sector first, then allocation budget
    # Sector concentration is now shown rather than enforced. The screen's job is to
    # surface every qualifying setup; whether a second name in a group is one idea or
    # two is a judgement to make at the chart, not a rule that hides candidates.
    book_sector_count = {}
    for _tk, _info in open_book.items():
        _s = UNIVERSE_SECTORS.get(_tk) or _info.get("sector") or "Other"
        book_sector_count[_s] = book_sector_count.get(_s, 0) + 1

    chosen, alloc = [], 0.0
    for r in hits:
        r["sector_held"] = book_sector_count.get(r["sec"], 0)
        size = r["size"]
        if alloc + size > 100.0:
            size = max(0.0, 100.0 - alloc)
        if size < 2.0 and not r["held"]:
            continue
        r = dict(r, size=size)
        alloc += size if not r["held"] else 0.0
        chosen.append(r)

    st.caption(("Data through the close of %s. " % asof.strftime("%a %b %d")) if asof else ""
               + ("The current session is excluded until it settles, so this list will not change during the day. "
                  if session_live else "")
               + "Scanned %d names. %d setup%s qualified."
               % (len(data), len(hits), "" if len(hits) == 1 else "s"))

    if not chosen:
        st.info("Nothing qualifies today. That is a valid result: with no clean pullbacks on offer, "
                "the honest answer is no trade rather than a lower bar.")
    else:
        rows = ""
        for r in chosen:
            t1, t2, t3 = (list(r["tg"]) + [None, None, None])[:3]
            sz = "{:.1f}%".format(r["size"]) + ("*" if r["capped"] else "")
            _shares = {"50 / 25 / 25": (50, 25, 25), "All out at T1": (100, 0, 0),
                       "Thirds": (33, 33, 34), "50 / 50 at T2": (50, 50, 0)}[scale_plan]
            _plan = " / ".join(str(s) + "%" for s in _shares if s > 0)
            _mark = ""
            if r.get("sector_held") and not r["held"]:
                _mark += ("<span style='border:1px solid " + AMBER + "; color:" + AMBER + "; font-size:9.5px; "
                          "font-weight:600; padding:1px 6px; border-radius:4px; margin-left:8px;'>"
                          + ("HOLD %d IN SECTOR" % r["sector_held"]) + "</span>")
            if r["held"]:
                _mark = ("<span style='border:1px solid " + AMBER + "; color:" + AMBER + "; font-size:9.5px; "
                         "font-weight:600; padding:1px 6px; border-radius:4px; margin-left:8px;'>IN BOOK @ "
                         + "{:,.2f}".format(r["book_entry"]) + "</span>")
            rows += ("<tr><td style='font-weight:700;'>" + r["t"] + _mark + "</td>"
                     "<td style='color:" + MUTED + ";'>" + r["sec"] + "</td>"
                     "<td style='text-align:right;'>" + "{:,.2f}".format(r["px"]) + "</td>"
                     "<td style='text-align:right;color:" + RED + ";'>" + "{:,.2f}".format(r["stop"]) + "</td>"
                     "<td style='text-align:right;color:" + GREEN + ";'>" + "{:,.2f}".format(t1) + "</td>"
                     "<td style='text-align:right;color:" + MUTED + ";'>" + ("{:,.2f}".format(t2) if t2 else "—") + "</td>"
                     "<td style='text-align:right;color:" + MUTED + ";'>" + ("{:,.2f}".format(t3) if t3 else "—") + "</td>"
                     "<td style='text-align:right;font-weight:700;color:" + AMBER + ";'>" + "{:.1f}".format(r["rr"]) + "</td>"
                     "<td style='text-align:right;'>" + sz + "</td>"
                     "<td style='text-align:right;color:" + MUTED + ";'>" + "{:+.1f}%".format(r["ext"]) + "</td>"
                     "<td style='text-align:right;color:" + (AMBER if r["stop_atr"] < 1.0 else MUTED) + ";'>"
                     + "{:.2f}".format(r["stop_atr"]) + "</td>"
                     "<td style='text-align:right;color:" + (AMBER if r["atr_t1"] > 20 else MUTED) + ";'>"
                     + "{:.0f}".format(r["atr_t1"]) + "</td>"
                     "<td style='text-align:right;color:" + MUTED + ";'>" + _plan + "</td></tr>")
        st.markdown("<table class='ns-tbl'><tr>"
                    "<th style='text-align:left;'>Ticker</th><th style='text-align:left;'>Sector</th>"
                    "<th style='text-align:right;'>Entry</th><th style='text-align:right;'>Stop</th>"
                    "<th style='text-align:right;'>T1</th><th style='text-align:right;'>T2</th>"
                    "<th style='text-align:right;'>T3</th><th style='text-align:right;'>R:R</th>"
                    "<th style='text-align:right;'>Size</th><th style='text-align:right;'>vs 21MA</th>"
                    "<th style='text-align:right;'>Stop ATRs</th><th style='text-align:right;'>ATRs to T1</th>"
                    "<th style='text-align:right;'>Scale out</th>"
                    "</tr>" + rows + "</table>", unsafe_allow_html=True)

        # Two different scopes were being mixed here: the candidates in the table above,
        # and everything already held in the book. Report them separately.
        new_rows = [r for r in chosen if not r["held"]]
        new_alloc = sum(r["size"] for r in new_rows)
        new_risk = sum(r["size"] / 100.0 * (abs(r["px"] - r["stop"]) / r["px"]) * 100.0 for r in new_rows)
        new_sectors = len({r["sec"] for r in new_rows})
        book_sectors = len({(UNIVERSE_SECTORS.get(tk) or info.get("sector") or "Other")
                            for tk, info in open_book.items()})
        alloc_col = GREEN if new_alloc <= 100 else RED

        st.markdown("<div class='ns-row' style='margin-top:10px;'>"
                    + tile("New Ideas", str(len(new_rows)),
                           "%d already in the book" % (len(chosen) - len(new_rows)),
                           GREEN if new_rows else MUTED)
                    + tile("If All Taken", "{:.0f}%".format(new_alloc),
                           "added to the book, new ideas only", alloc_col)
                    + tile("Added Risk", "{:.1f}%".format(new_risk),
                           "if every new stop hit", AMBER)
                    + tile("Already Open", str(len(open_book)),
                           "positions across %d sector%s" % (book_sectors, "" if book_sectors == 1 else "s"))
                    + tile("New Idea Sectors", str(new_sectors),
                           "groups the new ideas sit in")
                    + "</div>", unsafe_allow_html=True)

        st.markdown("<div class='ns-panel' style='margin-top:8px;border-left:3px solid " + BLUE + ";'>"
                    "<span style='font-size:13.5px;color:#cdd8e4;'><strong>Size</strong> is the position as a percentage "
                    "of the book so that a stop-out costs about " + "{:.2f}%".format(risk_pct) + " of it. A wide stop "
                    "earns a small position, which keeps risk constant instead of letting the stop distance set it. "
                    "An asterisk means the risk math justified more but the position cap applied. <strong>Stops</strong> "
                    "sit under the swing low that produced the pullback; <strong>targets</strong> are prior pivot highs, "
                    "or fib extensions where price is in blue sky. A row marked <strong>IN BOOK</strong> is a position you "
                    "already hold: its entry and targets are recalculated from the latest close, so they will not "
                    "match your fill. <strong>Stop ATRs</strong> is how far the stop sits from entry in average daily ranges: "
                    "under about 1.0 and ordinary noise takes it out, which also flatters the R:R. "
                    "<strong>ATRs to T1</strong> is the distance to the first "
                    "target measured in average daily ranges, which is roughly the number of sessions it would take: "
                    "a $75 target on a volatile $400 stock can be nearer in practice than a $20 target on a quiet one. "
                    "<strong>Scale out</strong> is the share of the position taken at T1, T2 and T3. "
                    "The stop moves to breakeven as soon as T1 fills, which matters more to the result than the "
                    "ratio does.</span></div>", unsafe_allow_html=True)

    st.markdown("<p style='color:" + MUTED + "; font-size:11.5px; text-align:center; margin-top:16px;'>"
                "A screen is a starting point, not a trade list. Check earnings dates before entering anything. "
                "This is not trading advice. This is purely for information/education.</p>", unsafe_allow_html=True)