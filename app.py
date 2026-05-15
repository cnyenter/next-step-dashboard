import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import math
import re

# 1. Page Configuration
st.set_page_config(page_title="Next Step Trading", layout="wide")
st.markdown("<style>.block-container { padding-top: 1rem; padding-bottom: 1rem; }</style>", unsafe_allow_html=True)

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

# 3. Fetch Market Data
@st.cache_data(ttl=300)
def get_market_data(ticker, period, interval):
    main_asset = yf.Ticker(ticker).history(period=period, interval=interval)
    nq = yf.Ticker("NQ=F").history(period="2d", interval="15m")
    btc = yf.Ticker("BTC-USD").history(period="2d", interval="15m")
    vix = yf.Ticker("^VIX").history(period="1d")
    return main_asset, nq, btc, vix

df_main, df_nq, df_btc, df_vix = get_market_data(active_ticker, api_period, api_interval)

if df_main.empty:
    st.error("⚠️ Data temporarily unavailable.")
    st.stop()

latest_price = df_main['Close'].iloc[-1]
live_vix = df_vix['Close'].iloc[-1]
daily_pct_move = (live_vix / math.sqrt(252)) / 100
expected_move_points = latest_price * daily_pct_move
em_upper, em_lower = latest_price + expected_move_points, latest_price - expected_move_points

# 4. Top Vitals Header
st.markdown("### 📊 Live Market Vitals")
col1, col2, col3, col4 = st.columns(4)
col1.metric(label=f"{asset_label} (Live)", value=f"{latest_price:,.2f}")
col2.metric(label="Volatility Index (VIX)", value=f"{live_vix:.2f}")
col3.metric(label="Implied Daily Move", value=f"± {expected_move_points:.1f} pts")
col4.metric(label="Implied Daily Range", value=f"{em_lower:.0f} - {em_upper:.0f}")

st.divider()

# 5. Database Connections
SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?output=csv"
MQ_SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?gid=1464368299&single=true&output=csv"

# Load Primary S/R Levels
try:
    levels_df = pd.read_csv(SHEET_URL)
    filtered_levels = levels_df[levels_df['Ticker'] == active_ticker]
except:
    filtered_levels = pd.DataFrame()

# Load and Parse MenthorQ Raw Text securely into a Dictionary
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
                # THE FIX: Split by the specific value string to preserve the "0" in 0DTE
                name = line.rsplit(val_str, 1)[0].strip() 
                mq_dict[name] = val
except:
    pass 

# 6. Build the Visual "Dealer Proximity Radar"
call_res = next((val for key, val in mq_dict.items() if "Call Resistance" in key and "0DTE" not in key), None)
put_sup = next((val for key, val in mq_dict.items() if "Put Support" in key and "0DTE" not in key), None)
hvl = next((val for key, val in mq_dict.items() if "HVL" in key or "High Vol Level" in key), None)
dte_call = next((val for key, val in mq_dict.items() if "0DTE Call" in key), None)
dte_put = next((val for key, val in mq_dict.items() if "0DTE Put" in key), None)

if call_res and put_sup:
    st.markdown("### 🎯 Dealer Proximity Radar")
    
    all_gauge_vals = [val for val in [put_sup, call_res, hvl, dte_call, dte_put, latest_price] if val is not None]
    min_range = min(all_gauge_vals) - 15
    max_range = max(all_gauge_vals) + 15

    gauge_steps = [
        {'range': [min_range, put_sup], 'color': "rgba(0, 255, 255, 0.15)"},
        {'range': [put_sup, call_res], 'color': "rgba(128, 128, 128, 0.1)"}, 
        {'range': [call_res, max_range], 'color': "rgba(255, 0, 255, 0.15)"} 
    ]
    
    # Overlay 0DTE as bright, solid 10-point bands for maximum visibility
    if dte_put:
        gauge_steps.append({'range': [dte_put - 5, dte_put + 5], 'color': "#00FFFF"})
    if dte_call:
        gauge_steps.append({'range': [dte_call - 5, dte_call + 5], 'color': "#FF00FF"})

    fig_gauge = go.Figure(go.Indicator(
        mode = "number+gauge",
        value = latest_price,
        domain = {'x': [0.1, 1], 'y': [0, 1]},
        title = {'text': "<b>Live Price</b>", 'font': {"color": "white", "size": 16}},
        number = {'font': {"color": "white"}},
        gauge = {
            'shape': "bullet",
            'axis': {'range': [min_range, max_range], 'tickfont': {"color": "white"}},
            'bar': {'color': "white", 'thickness': 0.1},
            'steps': gauge_steps,
            'threshold': {
                'line': {'color': "yellow", 'width': 3},
                'thickness': 0.75,
                'value': hvl if hvl else (call_res + put_sup)/2
            }
        }
    ))
    fig_gauge.update_layout(height=150, margin=dict(t=20, b=20, l=100, r=20), template="plotly_dark", paper_bgcolor='#111111', plot_bgcolor='#111111')
    st.plotly_chart(fig_gauge, theme=None, use_container_width=True)
    
    st.markdown("<p style='text-align: center; color: gray; font-size: 14px;'><i>Yellow Line = High Vol Level (HVL). Translucent blocks = Core Walls. Solid bright bands = 0DTE Walls.</i></p>", unsafe_allow_html=True)
    st.divider()

# 7. Chart Construction (Main Price Chart)
fig = go.Figure(data=[go.Candlestick(x=df_main.index, open=df_main['Open'], high=df_main['High'], low=df_main['Low'], close=df_main['Close'], name=asset_label)])

for index, row in filtered_levels.iterrows():
    zone_type, bottom, top = row['Type'], row['Bottom'], row['Top']
    fill_color, border_color = ("#00FF00", "#00CC00") if zone_type == "Support" else ("#FF0000", "#CC0000")
    fig.add_hrect(y0=bottom, y1=top, line_width=1, line_color=border_color, fillcolor=fill_color, opacity=0.35, annotation_text=zone_type, annotation_position="top left", annotation_font=dict(color="white", size=12))

fig.add_hline(y=em_upper, line_dash="dash", line_color="#00BFFF", line_width=1.5, annotation_text="+1 SD", annotation_position="bottom left", annotation_font=dict(color="white"), annotation_bgcolor="#00BFFF")
fig.add_hline(y=em_lower, line_dash="dash", line_color="#00BFFF", line_width=1.5, annotation_text="-1 SD", annotation_position="top left", annotation_font=dict(color="white"), annotation_bgcolor="#00BFFF")

fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=700, yaxis=dict(side="right"), paper_bgcolor='#111111', plot_bgcolor='#111111', margin=dict(l=10, r=10, t=30, b=10))
st.plotly_chart(fig, theme=None, use_container_width=True)

st.divider()

# 8. Macro Engines
st.markdown("### 🌐 Macro Liquidity & Risk Engine")
macro_col1, macro_col2 = st.columns(2)

def build_mini_chart(df, title, line_color):
    fig_mini = go.Figure(go.Scatter(x=df.index, y=df['Close'], mode='lines', line=dict(color=line_color, width=2)))
    fig_mini.update_layout(title=dict(text=title, font=dict(size=14, color="white")), xaxis_rangeslider_visible=False, template="plotly_dark", height=300, paper_bgcolor='#111111', plot_bgcolor='#111111', margin=dict(l=10, r=10, t=40, b=10), yaxis=dict(side="right"))
    return fig_mini

with macro_col1: st.plotly_chart(build_mini_chart(df_nq, "Nasdaq-100 (NQ_F)", "#FF9900"), theme=None, use_container_width=True)
with macro_col2: st.plotly_chart(build_mini_chart(df_btc, "Bitcoin (BTC-USD)", "#00FFCC"), theme=None, use_container_width=True)