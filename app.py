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
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

st_autorefresh(interval=60000, key="data_refresh")

def tile(label, value, sub="", color=TEXT):
    return ("<div class='ns-tile'><div class='ns-label'>" + label + "</div>"
            "<div class='ns-value' style='color:" + color + ";'>" + value + "</div>"
            "<div class='ns-sub'>" + sub + "</div></div>")

# ==========================================
# 2. SIDEBAR NAVIGATION ROUTER
# ==========================================
st.sidebar.title("🧭 Navigation")
page_selection = st.sidebar.radio("Select View:", ["Live Cockpit", "Swing Book"])
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
        main_asset = yf.Ticker(ticker).history(period=period, interval=interval)
        oil = yf.Ticker("CL=F").history(period="2d", interval="15m")
        vix = yf.Ticker("^VIX").history(period="2d", interval="15m")
        tf_15m = yf.Ticker(ticker).history(period="5d", interval="15m")
        tf_1h = yf.Ticker(ticker).history(period="1mo", interval="1h")
        tf_1d = yf.Ticker(ticker).history(period="6mo", interval="1d")
        return main_asset, oil, vix, tf_15m, tf_1h, tf_1d

    @st.cache_data(ttl=50)
    def get_basis_prices():
        out = {}
        for sym in ["ES=F", "^SPX"]:
            try:
                h = yf.Ticker(sym).history(period="1d", interval="1m")
                if not h.empty:
                    out[sym] = float(h["Close"].iloc[-1])
            except Exception:
                pass
        return out

    df_main, df_oil, df_vix, df_15m, df_1h, df_1d = get_market_data(active_ticker, api_period, api_interval)

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
    try:
        levels_df = pd.read_csv(SHEET_URL)
        filtered_levels = levels_df[levels_df['Ticker'] == active_ticker]
    except Exception:
        filtered_levels = pd.DataFrame()
        levels_note = "Levels sheet unavailable — zones and ladder hidden."
    if levels_note:
        st.caption(levels_note)

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

        mk = ""
        for i, (name, val, color) in enumerate(marks):
            x = "{:.1f}".format(rpct(val))
            if i % 2 == 0:
                mk += ("<div style='position:absolute; left:" + x + "%; top:0; transform:translateX(-50%); text-align:center; width:96px;'>"
                       "<div style='color:" + color + "; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>" + name + "</div>"
                       "<div style='color:" + TEXT + "; font-family:IBM Plex Mono,monospace; font-size:14px; font-weight:600;'>" + "{:,.0f}".format(val) + "</div>"
                       "<div style='width:2px; height:14px; background:" + color + "; margin:2px auto 0;'></div></div>")
            else:
                mk += ("<div style='position:absolute; left:" + x + "%; top:50px; transform:translateX(-50%); text-align:center; width:96px;'>"
                       "<div style='width:2px; height:14px; background:" + color + "; margin:0 auto 2px;'></div>"
                       "<div style='color:" + TEXT + "; font-family:IBM Plex Mono,monospace; font-size:14px; font-weight:600;'>" + "{:,.0f}".format(val) + "</div>"
                       "<div style='color:" + color + "; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;'>" + name + "</div></div>")

        lp = "{:.1f}".format(rpct(latest_price))
        mk += ("<div style='position:absolute; left:" + lp + "%; top:26px; transform:translateX(-50%); text-align:center; z-index:3;'>"
               "<div style='background:" + BLUE + "; color:white; font-family:IBM Plex Mono,monospace; font-size:14px; font-weight:600; padding:2px 8px; border-radius:4px; white-space:nowrap;'>" + "{:,.1f}".format(latest_price) + "</div>"
               "<div style='width:2px; height:18px; background:white; margin:1px auto 0;'></div></div>")

        radar = ("<div class='ns-panel' style='padding:14px 40px 10px;'>"
                 "<div style='position:relative; height:104px;'>"
                 "<div style='position:absolute; top:44px; left:0; right:0; height:6px; background:#222a38; border-radius:3px;'></div>"
                 + zones + mk + "</div></div>")
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

    # --- Lock the y-axis to the price action so level zones cannot flatten the candles ---
    p_hi, p_lo = float(df_main['High'].max()), float(df_main['Low'].min())
    pad = max((p_hi - p_lo) * 0.10, expected_move_points * 0.35)
    y_hi, y_lo = p_hi + pad, p_lo - pad

    # Draw only the zones that are actually in view, clipped to the visible window
    visible_zones = []
    for _, row in filtered_levels.iterrows():
        try:
            zone_type, bottom, top = row['Type'], float(row['Bottom']), float(row['Top'])
        except Exception:
            continue
        if bottom > top:
            bottom, top = top, bottom
        if top < y_lo or bottom > y_hi:
            continue
        visible_zones.append((str(zone_type).strip().lower() == "support", bottom, top))

    # Stagger labels so stacked zones do not overprint each other
    visible_zones.sort(key=lambda z: z[1])
    last_label_y, x_slots, slot = None, [0.005, 0.13, 0.26], 0
    for is_sup, bottom, top in visible_zones:
        fill_color = GREEN if is_sup else RED
        mid = (bottom + top) / 2.0
        if last_label_y is not None and abs(mid - last_label_y) < (y_hi - y_lo) * 0.05:
            slot = (slot + 1) % len(x_slots)
        else:
            slot = 0
        last_label_y = mid
        fig.add_hrect(y0=max(bottom, y_lo), y1=min(top, y_hi), line_width=1, line_color=fill_color,
                      fillcolor=fill_color, opacity=0.11, layer="below")
        fig.add_annotation(xref="paper", x=x_slots[slot], y=min(top, y_hi), yanchor="top", xanchor="left",
                           text=("S " if is_sup else "R ") + "{:,.0f}".format(mid),
                           showarrow=False, font=dict(color="white", size=12),
                           bgcolor="rgba(13,17,23,0.75)", borderpad=2)

    for y_val, tag in [(em_upper, "+1 SD"), (em_lower, "-1 SD")]:
        fig.add_hline(y=y_val, line_dash="dash", line_color="#00BFFF", line_width=1.2)
        fig.add_annotation(xref="paper", x=0.995, y=y_val, xanchor="right", yanchor="middle", text=tag,
                           showarrow=False, font=dict(color="white", size=12), bgcolor="#00BFFF", borderpad=3)

    fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=620,
                      yaxis=dict(side="right", range=[y_lo, y_hi], tickfont=dict(size=13)),
                      xaxis=dict(tickfont=dict(size=13)),
                      paper_bgcolor=BG, plot_bgcolor="#10151f",
                      margin=dict(l=10, r=10, t=34, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                                  bgcolor="rgba(0,0,0,0)", font=dict(size=13)))
    st.plotly_chart(fig, theme=None, use_container_width=True)

    # ---- Distance to Your Levels ladder ----
    if not filtered_levels.empty:
        st.markdown("<div class='ns-section'>📏 Distance To The Published Levels</div>", unsafe_allow_html=True)
        rows = []
        for _, row in filtered_levels.iterrows():
            try:
                mid = (float(row['Bottom']) + float(row['Top'])) / 2.0
                rows.append((str(row['Type']).strip().title(), float(row['Bottom']), float(row['Top']), mid))
            except Exception:
                continue
        above = sorted([r for r in rows if r[3] >= latest_price], key=lambda r: r[3])[:4]
        below = sorted([r for r in rows if r[3] < latest_price], key=lambda r: -r[3])[:4]

        def ladder_row(r, nearest):
            typ, bottom, top, mid = r
            color = GREEN if typ == "Support" else RED
            dist = mid - latest_price
            border = "border:1px solid " + (BLUE if nearest else LINE) + ";"
            zone = "{:,.0f}".format(mid) if abs(top - bottom) < 1 else "{:,.0f} – {:,.0f}".format(bottom, top)
            return ("<div style='display:flex; align-items:center; background:" + PANEL2 + "; " + border +
                    " border-radius:6px; padding:10px 14px; margin-bottom:7px;'>"
                    "<span style='width:10px; height:10px; border-radius:50%; background:" + color + "; margin-right:11px;'></span>"
                    "<span style='color:" + TEXT + "; font-size:15px;'>" + typ + " <span style='font-family:IBM Plex Mono,monospace; font-weight:600;'>" + zone + "</span></span>"
                    "<span style='margin-left:auto; font-family:IBM Plex Mono,monospace; font-size:15px; font-weight:600; color:" + (GREEN if dist >= 0 else RED) + ";'>"
                    + "{:+.1f} pts".format(dist) + "</span></div>")

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

    @st.cache_data(ttl=60)
    def get_live_prices(tickers):
        prices = {}
        for t in tickers:
            try:
                h = yf.Ticker(t).history(period="2d")
                if not h.empty:
                    prices[t] = float(h["Close"].iloc[-1])
            except Exception:
                pass
        return prices

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
    else:
        wins = closed_df[closed_df["Result %"] > 0]
        losses = closed_df[closed_df["Result %"] <= 0]
        win_rate = len(wins) / len(closed_df) * 100.0
        avg_w = wins["Result %"].mean() if not wins.empty else 0.0
        avg_l = losses["Result %"].mean() if not losses.empty else 0.0
        total = closed_df["Result %"].sum()
        tiles = (
            tile("Closed Trades", str(len(closed_df)), str(len(wins)) + "W — " + str(len(losses)) + "L")
            + tile("Win Rate", "%.0f%%" % win_rate, "since " + BOOK_OPENED, GREEN if win_rate >= 50 else RED)
            + tile("Avg Winner", "+%.1f%%" % avg_w, "vs %.1f%% avg loser" % avg_l, GREEN)
            + tile("Sum of Results", "%+.1f%%" % total, "closed trades, unweighted", GREEN if total >= 0 else RED)
        )
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
                pnl_html = "<span style='margin-left:auto; font-weight:bold; font-size:16px; color:" + pnl_color + ";'>%+.1f%%</span>" % pnl
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
        show = closed_df[["Ticker", "Side", "Date_Opened", "Entry", "Date_Closed", "Exit_Price", "Result %"]].copy()
        show = show.sort_values("Date_Closed", ascending=False)
        show["Result %"] = show["Result %"].map(lambda v: "%+.1f%%" % v)
        st.dataframe(show, use_container_width=True, hide_index=True)

    st.markdown("<p style='color:" + MUTED + "; font-size:11px; text-align:center; margin-top:18px;'>"
                "This is not trading advice. This is purely for information/education. Positions reflect the author's own tracking portfolio.</p>", unsafe_allow_html=True)