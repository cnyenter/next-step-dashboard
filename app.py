import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import math

# 1. Page Configuration
st.set_page_config(page_title="Next Step Trading", layout="wide")
st.markdown("<style>.block-container { padding-top: 1rem; padding-bottom: 1rem; }</style>", unsafe_allow_html=True)

# 2. Sidebar Navigation for Asset Selection
st.sidebar.title("🎛️ Dashboard Controls")
selected_asset = st.sidebar.radio("Select Active Asset:", ["E-mini Futures (ES_F)", "S&P 500 Index (SPX)"])

# Map UI selection to actual Yahoo Finance ticker symbols
if selected_asset == "E-mini Futures (ES_F)":
    active_ticker = "ES=F"
    asset_label = "ES_F"
else:
    active_ticker = "^SPX"
    asset_label = "SPX"

st.title(f"Next Step Trading: Daily Live Cockpit ({asset_label})")

# 3. Fetch Core Data Dynamically Based on Sidebar Choice
@st.cache_data(ttl=300)
def get_market_data(ticker):
    main_asset = yf.Ticker(ticker).history(period="5d", interval="15m")
    nq = yf.Ticker("NQ=F").history(period="2d", interval="15m")
    btc = yf.Ticker("BTC-USD").history(period="2d", interval="15m")
    vix = yf.Ticker("^VIX").history(period="1d")
    return main_asset, nq, btc, vix

df_main, df_nq, df_btc, df_vix = get_market_data(active_ticker)

# Metrics calculations
latest_price = df_main['Close'].iloc[-1]
live_vix = df_vix['Close'].iloc[-1]
daily_pct_move = (live_vix / math.sqrt(252)) / 100
expected_move_points = latest_price * daily_pct_move
em_upper, em_lower = latest_price + expected_move_points, latest_price - expected_move_points

# 4. Top Dashboard Header
st.markdown("### 📊 Live Market Vitals")
col1, col2, col3, col4 = st.columns(4)
col1.metric(label=f"{asset_label} (Live)", value=f"{latest_price:,.2f}")
col2.metric(label="Volatility Index (VIX)", value=f"{live_vix:.2f}")
col3.metric(label="Implied Daily Move", value=f"± {expected_move_points:.1f} pts")
col4.metric(label="Implied Daily Range", value=f"{em_lower:.0f} - {em_upper:.0f}")

st.divider()

# 5. Main Chart: Read Google Sheet and Filter by Ticker
SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?output=csv"
try:
    levels_df = pd.read_csv(SHEET_URL)
    # Filter the rows to only include levels matching the active sidebar choice
    filtered_levels = levels_df[levels_df['Ticker'] == active_ticker]
except Exception as e:
    st.error("Could not read the Google Sheet. Double check your link and column headers!")
    st.stop()

# Build Primary Chart
fig = go.Figure(data=[go.Candlestick(x=df_main.index,
                open=df_main['Open'], high=df_main['High'],
                low=df_main['Low'], close=df_main['Close'], name=asset_label)])

# Draw Filtered Zones
for index, row in filtered_levels.iterrows():
    zone_type, bottom, top = row['Type'], row['Bottom'], row['Top']
    fill_color, border_color = ("#00FF00", "#00CC00") if zone_type == "Support" else ("#FF0000", "#CC0000")
    fig.add_hrect(y0=bottom, y1=top, line_width=1, line_color=border_color, fillcolor=fill_color, opacity=0.35, annotation_text=zone_type, annotation_position="top left", annotation_font=dict(color="white", size=12))

# Draw Expected Moves
fig.add_hline(y=em_upper, line_dash="dash", line_color="#00BFFF", line_width=1.5, annotation_text="Upper Expected Move (+1 SD)", annotation_position="bottom left", annotation_font=dict(color="#00BFFF", size=11))
fig.add_hline(y=em_lower, line_dash="dash", line_color="#00BFFF", line_width=1.5, annotation_text="Lower Expected Move (-1 SD)", annotation_position="top left", annotation_font=dict(color="#00BFFF", size=11))

fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=600, yaxis=dict(side="right"), paper_bgcolor='#111111', plot_bgcolor='#111111', margin=dict(l=10, r=10, t=30, b=10))
st.plotly_chart(fig, theme=None, use_container_width=True)

st.divider()

# 6. Macro Engines
st.markdown("### 🌐 Macro Liquidity & Risk Engine")
macro_col1, macro_col2 = st.columns(2)

def build_mini_chart(df, title, line_color):
    fig_mini = go.Figure(go.Scatter(x=df.index, y=df['Close'], mode='lines', line=dict(color=line_color, width=2)))
    fig_mini.update_layout(title=dict(text=title, font=dict(size=14, color="white")), xaxis_rangeslider_visible=False, template="plotly_dark", height=300, paper_bgcolor='#111111', plot_bgcolor='#111111', margin=dict(l=10, r=10, t=40, b=10), yaxis=dict(side="right"))
    return fig_mini

with macro_col1:
    st.plotly_chart(build_mini_chart(df_nq, "Nasdaq-100 Futures (NQ_F Trend)", "#FF9900"), theme=None, use_container_width=True)
with macro_col2:
    st.plotly_chart(build_mini_chart(df_btc, "Bitcoin / Global Risk (BTC-USD Trend)", "#00FFCC"), theme=None, use_container_width=True)