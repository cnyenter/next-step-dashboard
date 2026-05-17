import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import math
import re
from streamlit_autorefresh import st_autorefresh

# 1. Page Configuration & Auto-Refresh Heartbeat
st.set_page_config(page_title="Next Step Trading", layout="wide")
st.markdown("<style>.block-container { padding-top: 1rem; padding-bottom: 1rem; }</style>", unsafe_allow_html=True)

# Ping Yahoo Finance and refresh the page every 60 seconds automatically
st_autorefresh(interval=60000, key="data_refresh")

# 2. Sidebar Controls
st.sidebar.title("🎛️ Dashboard Controls")
selected_asset = st.sidebar.radio("Select Active Asset:", ["E-mini Futures (ES_F)", "S&P 500 Index (SPX)"])
selected_timeframe = st.sidebar.selectbox("Select Candle Interval:", ["1-Minute", "5-Minute", "15-Minute", "1-Hour", "Daily"], index=2)

if selected_asset == "E-mini Futures (ES_F)":
    active_ticker, asset_label = "ES=F", "ES_F"
else:
    active_ticker, asset_label = "^SPX", "SPX"

if "1-Minute" in selected_timeframe: api_interval, api_period = "1m", "5d"
elif "5-Minute" in selected_timeframe: api_interval, api_period = "5m", "5d"
elif "15-Minute" in selected_timeframe: api_interval, api_period = "15m", "5d"
elif "1-Hour" in selected_timeframe: api_interval, api_period = "1h", "10d"
else: api_interval, api_period = "1d", "3mo"

st.title(f"Next Step Trading: Daily Live Cockpit ({asset_label})")

# 3. Fetch Market Data & MTF Sentiment Data
@st.cache_data(ttl=50) # Cache set slightly lower than auto-refresh to ensure fresh pulls
def get_market_data(ticker, period, interval):
    # Main Asset Data
    main_asset = yf.Ticker(ticker).history(period=period, interval=interval)
    
    # Macro Data (Oil and VIX)
    oil = yf.Ticker("CL=F").history(period="2d", interval="15m")
    vix = yf.Ticker("^VIX").history(period="2d", interval="15m") # Intraday VIX
    
    # Multi-Timeframe Data for Confluence Engine
    tf_15m = yf.Ticker(ticker).history(period="5d", interval="15m")
    tf_1h = yf.Ticker(ticker).history(period="1mo", interval="1h")
    tf_1d = yf.Ticker(ticker).history(period="6mo", interval="1d")
    
    return main_asset, oil, vix, tf_15m, tf_1h, tf_1d

df_main, df_oil, df_vix, df_15m, df_1h, df_1d = get_market_data(active_ticker, api_period, api_interval)

if df_main.empty:
    st.error("⚠️ Data temporarily unavailable.")
    st.stop()

latest_price = df_main['Close'].iloc[-1]
latest_vix = df_vix['Close'].iloc[-1] if not df_vix.empty else 15.0
daily_pct_move = (latest_vix / math.sqrt(252)) / 100
expected_move_points = latest_price * daily_pct_move
em_upper, em_lower = latest_price + expected_move_points, latest_price - expected_move_points

# 4. Top Vitals Header
st.markdown("### 📊 Live Market Vitals")
col1, col2, col3, col4 = st.columns(4)
col1.metric(label=f"{asset_label} (Live)", value=f"{latest_price:,.2f}")
col2.metric(label="Volatility Index (VIX)", value=f"{latest_vix:.2f}")
col3.metric(label="Implied Daily Move", value=f"± {expected_move_points:.1f} pts")
col4.metric(label="Implied Daily Range", value=f"{em_lower:.0f} - {em_upper:.0f}")

st.divider()

# 5. Database Connections (Insert Links Here)
SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?output=csv"
MQ_SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?output=csv"

try:
    levels_df = pd.read_csv(SHEET_URL)
    filtered_levels = levels_df[levels_df['Ticker'] == active_ticker]
except:
    filtered_levels = pd.DataFrame()

mq_dict = {}
try:
    mq_df = pd.read_csv(MQ_SHEET_URL, header=None)
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
except:
    pass 

# 6. Dealer Proximity Radar
call_res = next((val for key, val in mq_dict.items() if "Call Resistance" in key and "0DTE" not in key), None)
put_sup = next((val for key, val in mq_dict.items() if "Put Support" in key and "0DTE" not in key), None)
hvl = next((val for key, val in mq_dict.items() if "HVL" in key or "High Vol Level" in key), None)
dte_call = next((val for key, val in mq_dict.items() if "0DTE Call" in key), None)
dte_put = next((val for key, val in mq_dict.items() if "0DTE Put" in key), None)

if call_res and put_sup:
    st.markdown("### 🎯 Dealer Proximity Radar")
    all_gauge_vals = [val for val in [put_sup, call_res, hvl, dte_call, dte_put, latest_price] if val is not None]
    min_range, max_range = min(all_gauge_vals) - 15, max(all_gauge_vals) + 15

    gauge_steps = [
        {'range': [min_range, put_sup], 'color': "rgba(0, 255, 255, 0.15)"},
        {'range': [put_sup, call_res], 'color': "rgba(128, 128, 128, 0.1)"}, 
        {'range': [call_res, max_range], 'color': "rgba(255, 0, 255, 0.15)"} 
    ]
    if dte_put: gauge_steps.append({'range': [dte_put - 5, dte_put + 5], 'color': "#00FFFF"})
    if dte_call: gauge_steps.append({'range': [dte_call - 5, dte_call + 5], 'color': "#FF00FF"})

    fig_gauge = go.Figure(go.Indicator(
        mode = "number+gauge", value = latest_price, domain = {'x': [0.1, 1], 'y': [0, 1]},
        title = {'text': "<b>Live Price</b>", 'font': {"color": "white", "size": 16}}, number = {'font': {"color": "white"}},
        gauge = {'shape': "bullet", 'axis': {'range': [min_range, max_range], 'tickfont': {"color": "white"}},
                 'bar': {'color': "white", 'thickness': 0.1}, 'steps': gauge_steps,
                 'threshold': {'line': {'color': "yellow", 'width': 3}, 'thickness': 0.75, 'value': hvl if hvl else (call_res + put_sup)/2}}
    ))
    fig_gauge.update_layout(height=150, margin=dict(t=20, b=20, l=100, r=20), template="plotly_dark", paper_bgcolor='#111111', plot_bgcolor='#111111')
    st.plotly_chart(fig_gauge, theme=None, use_container_width=True)
    st.divider()

# 7. Main Price Chart
fig = go.Figure(data=[go.Candlestick(x=df_main.index, open=df_main['Open'], high=df_main['High'], low=df_main['Low'], close=df_main['Close'], name=asset_label)])

for index, row in filtered_levels.iterrows():
    zone_type, bottom, top = row['Type'], row['Bottom'], row['Top']
    fill_color, border_color = ("#00FF00", "#00CC00") if zone_type == "Support" else ("#FF0000", "#CC0000")
    fig.add_hrect(y0=bottom, y1=top, line_width=1, line_color=border_color, fillcolor=fill_color, opacity=0.35, annotation_text=zone_type, annotation_position="top left", annotation_font=dict(color="white", size=12))

fig.add_hline(y=em_upper, line_dash="dash", line_color="#00BFFF", line_width=1.5, annotation_text="+1 SD", annotation_position="bottom left", annotation_font=dict(color="white"), annotation_bgcolor="#00BFFF")
fig.add_hline(y=em_lower, line_dash="dash", line_color="#00BFFF", line_width=1.5, annotation_text="-1 SD", annotation_position="top left", annotation_font=dict(color="white"), annotation_bgcolor="#00BFFF")

fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=600, yaxis=dict(side="right"), paper_bgcolor='#111111', plot_bgcolor='#111111', margin=dict(l=10, r=10, t=30, b=10))
st.plotly_chart(fig, theme=None, use_container_width=True)
st.divider()

# 8. NEW: Multi-Timeframe Trend Confluence Engine
st.markdown("### 🧲 Trend Confluence Engine (Price vs Moving Averages)")

def analyze_trend(df):
    if df.empty or len(df) < 50: return "Data Insufficient", "gray"
    
    # Calculate simple moving averages (20 fast, 50 slow)
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    
    curr_price = df['Close'].iloc[-1]
    sma_20 = df['SMA_20'].iloc[-1]
    sma_50 = df['SMA_50'].iloc[-1]
    
    # Logic: Bullish if Price > Fast MA > Slow MA. Bearish if inverse.
    if curr_price > sma_20 and sma_20 > sma_50: return "Strong Bullish", "#00FF00"
    elif curr_price < sma_20 and sma_20 < sma_50: return "Strong Bearish", "#FF0000"
    elif curr_price > sma_20: return "Weak Bullish / Choppy", "#8FBC8F"
    else: return "Weak Bearish / Choppy", "#CD5C5C"

trend_15m, color_15m = analyze_trend(df_15m)
trend_1h, color_1h = analyze_trend(df_1h)
trend_1d, color_1d = analyze_trend(df_1d)

tcol1, tcol2, tcol3 = st.columns(3)
with tcol1: st.markdown(f"<div style='text-align: center; padding: 10px; background-color: #222; border-radius: 5px; border-bottom: 5px solid {color_15m};'><b>15-Minute (Intraday)</b><br><span style='color: {color_15m}; font-size: 18px;'>{trend_15m}</span></div>", unsafe_allow_html=True)
with tcol2: st.markdown(f"<div style='text-align: center; padding: 10px; background-color: #222; border-radius: 5px; border-bottom: 5px solid {color_1h};'><b>1-Hour (Swing)</b><br><span style='color: {color_1h}; font-size: 18px;'>{trend_1h}</span></div>", unsafe_allow_html=True)
with tcol3: st.markdown(f"<div style='text-align: center; padding: 10px; background-color: #222; border-radius: 5px; border-bottom: 5px solid {color_1d};'><b>Daily (Macro)</b><br><span style='color: {color_1d}; font-size: 18px;'>{trend_1d}</span></div>", unsafe_allow_html=True)

st.divider()

# 9. Macro Engines (Now Candlesticks for Oil & VIX)
st.markdown("### 🌐 Macro Risk Engine (Crude Oil & VIX)")
macro_col1, macro_col2 = st.columns(2)

def build_candlestick_mini(df, title):
    fig_mini = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'])])
    fig_mini.update_layout(title=dict(text=title, font=dict(size=14, color="white")), xaxis_rangeslider_visible=False, template="plotly_dark", height=350, paper_bgcolor='#111111', plot_bgcolor='#111111', margin=dict(l=10, r=10, t=40, b=10), yaxis=dict(side="right"))
    return fig_mini

with macro_col1: st.plotly_chart(build_candlestick_mini(df_oil, "Crude Oil Futures (CL_F)"), theme=None, use_container_width=True)
with macro_col2: st.plotly_chart(build_candlestick_mini(df_vix, "Volatility Index (VIX)"), theme=None, use_container_width=True)