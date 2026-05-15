import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import math
import re

# 1. Page Configuration
st.set_page_config(page_title="Next Step Trading", layout="wide")
st.markdown("<style>.block-container { padding-top: 1rem; padding-bottom: 1rem; }</style>", unsafe_allow_html=True)

# 2. Sidebar Controls (Clean - No Text Box)
st.sidebar.title("🎛️ Dashboard Controls")
selected_asset = st.sidebar.radio("Select Active Asset:", ["E-mini Futures (ES_F)", "S&P 500 Index (SPX)"])

selected_timeframe = st.sidebar.selectbox(
    "Select Candle Interval:", 
    ["1-Minute (Surgical Execution)", "5-Minute (Intraday Trend)", "15-Minute (Default Anchor)", "1-Hour (Macro Intraday)", "Daily (Swing/Macro View)"],
    index=2
)

# 3. Process UI Selections
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

# 4. Fetch Market Data
@st.cache_data(ttl=300)
def get_market_data(ticker, period, interval):
    main_asset = yf.Ticker(ticker).history(period=period, interval=interval)
    nq = yf.Ticker("NQ=F").history(period="2d", interval="15m")
    btc = yf.Ticker("BTC-USD").history(period="2d", interval="15m")
    vix = yf.Ticker("^VIX").history(period="1d")
    return main_asset, nq, btc, vix

df_main, df_nq, df_btc, df_vix = get_market_data(active_ticker, api_period, api_interval)

if df_main.empty:
    st.error("⚠️ Selected timeframe data temporarily unavailable. Please choose another interval.")
    st.stop()

latest_price = df_main['Close'].iloc[-1]
live_vix = df_vix['Close'].iloc[-1]
daily_pct_move = (live_vix / math.sqrt(252)) / 100
expected_move_points = latest_price * daily_pct_move
em_upper, em_lower = latest_price + expected_move_points, latest_price - expected_move_points

# 5. Top Vitals Header
st.markdown("### 📊 Live Market Vitals")
col1, col2, col3, col4 = st.columns(4)
col1.metric(label=f"{asset_label} (Live)", value=f"{latest_price:,.2f}")
col2.metric(label="Volatility Index (VIX)", value=f"{live_vix:.2f}")
col3.metric(label="Implied Daily Move", value=f"± {expected_move_points:.1f} pts")
col4.metric(label="Implied Daily Range", value=f"{em_lower:.0f} - {em_upper:.0f}")

st.divider()

# 6. Database Connections
SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?output=csv"
MQ_SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?gid=1464368299&single=true&output=csv"

# Load Primary S/R Levels
try:
    levels_df = pd.read_csv(SHEET_URL)
    filtered_levels = levels_df[levels_df['Ticker'] == active_ticker]
except Exception as e:
    st.error("Could not read the primary S/R Google Sheet.")
    st.stop()

# Load MenthorQ Raw Text from Cell A1
mq_paste = ""
try:
    mq_df = pd.read_csv(MQ_SHEET_URL, header=None) # Tells Pandas not to look for column headers
    if not mq_df.empty:
        mq_paste = str(mq_df.iloc[0, 0]) # Grabs the raw text block from Cell A1
except Exception as e:
    pass # If the sheet is empty or failing, it just skips drawing the MenthorQ lines without breaking the app

# 7. Chart Construction
fig = go.Figure(data=[go.Candlestick(x=df_main.index, open=df_main['Open'], high=df_main['High'], low=df_main['Low'], close=df_main['Close'], name=asset_label)])

# Draw Primary S/R Zones
for index, row in filtered_levels.iterrows():
    zone_type, bottom, top = row['Type'], row['Bottom'], row['Top']
    fill_color, border_color = ("#00FF00", "#00CC00") if zone_type == "Support" else ("#FF0000", "#CC0000")
    fig.add_hrect(y0=bottom, y1=top, line_width=1, line_color=border_color, fillcolor=fill_color, opacity=0.35, annotation_text=zone_type, annotation_position="top left", annotation_font=dict(color="white", size=12))

# Parse and Draw MenthorQ Lines invisibly
if mq_paste:
    for line in mq_paste.split('\n'):
        if not line.strip(): continue
        numbers = re.findall(r'[\d,]+\.?\d*', line)
        if numbers:
            val = float(numbers[-1].replace(',', ''))
            
            if "0DTE Call" in line:
                fig.add_hline(y=val, line_dash="dot", line_color="#FF00FF", line_width=2, annotation_text="0DTE Call Wall", annotation_position="right", annotation_font=dict(color="#FF00FF"))
            elif "0DTE Put" in line:
                fig.add_hline(y=val, line_dash="dot", line_color="#00FFFF", line_width=2, annotation_text="0DTE Put Wall", annotation_position="right", annotation_font=dict(color="#00FFFF"))
            elif "Call Resistance" in line:
                fig.add_hline(y=val, line_dash="solid", line_color="#FF00FF", line_width=2, annotation_text="Call Resistance", annotation_position="right", annotation_font=dict(color="#FF00FF"))
            elif "Put Support" in line:
                fig.add_hline(y=val, line_dash="solid", line_color="#00FFFF", line_width=2, annotation_text="Put Support", annotation_position="right", annotation_font=dict(color="#00FFFF"))
            elif "High Vol Level" in line or "HVL" in line:
                fig.add_hline(y=val, line_dash="solid", line_color="#FFD700", line_width=3, annotation_text="High Vol Level (HVL)", annotation_position="bottom right", annotation_font=dict(color="#FFD700"))

# Draw Expected Moves
fig.add_hline(y=em_upper, line_dash="dash", line_color="#00BFFF", line_width=1.5, annotation_text="Upper Expected Move (+1 SD)", annotation_position="bottom left", annotation_font=dict(color="#00BFFF", size=11))
fig.add_hline(y=em_lower, line_dash="dash", line_color="#00BFFF", line_width=1.5, annotation_text="Lower Expected Move (-1 SD)", annotation_position="top left", annotation_font=dict(color="#00BFFF", size=11))

fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=650, yaxis=dict(side="right"), paper_bgcolor='#111111', plot_bgcolor='#111111', margin=dict(l=10, r=10, t=30, b=10))
st.plotly_chart(fig, theme=None, use_container_width=True)

st.divider()

# 8. Macro Engines
st.markdown("### 🌐 Macro Liquidity & Risk Engine")
macro_col1, macro_col2 = st.columns(2)

def build_mini_chart(df, title, line_color):
    fig_mini = go.Figure(go.Scatter(x=df.index, y=df['Close'], mode='lines', line=dict(color=line_color, width=2)))
    fig_mini.update_layout(title=dict(text=title, font=dict(size=14, color="white")), xaxis_rangeslider_visible=False, template="plotly_dark", height=300, paper_bgcolor='#111111', plot_bgcolor='#111111', margin=dict(l=10, r=10, t=40, b=10), yaxis=dict(side="right"))
    return fig_mini

with macro_col1: st.plotly_chart(build_mini_chart(df_nq, "Nasdaq-100 Futures (NQ_F Trend)", "#FF9900"), theme=None, use_container_width=True)
with macro_col2: st.plotly_chart(build_mini_chart(df_btc, "Bitcoin / Global Risk (BTC-USD Trend)", "#00FFCC"), theme=None, use_container_width=True)