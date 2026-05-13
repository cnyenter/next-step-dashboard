import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import math

# 1. Page Configuration
st.set_page_config(page_title="Next Step Trading", layout="wide")

# Inject Custom CSS to remove dead space at the top of the browser window
st.markdown("""
    <style>
        .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
        }
    </style>
""", unsafe_allow_html=True)

st.title("Next Step Trading: Daily Live Cockpit")

# 2. Fetch Core and Macro Market Data
@st.cache_data(ttl=300)
def get_market_data():
    es = yf.Ticker("ES=F").history(period="5d", interval="15m")
    nq = yf.Ticker("NQ=F").history(period="2d", interval="15m")
    btc = yf.Ticker("BTC-USD").history(period="2d", interval="15m")
    vix = yf.Ticker("^VIX").history(period="1d")
    return es, nq, btc, vix

df_es, df_nq, df_btc, df_vix = get_market_data()

# Metrics calculations
latest_es = df_es['Close'].iloc[-1]
live_vix = df_vix['Close'].iloc[-1]
daily_pct_move = (live_vix / math.sqrt(252)) / 100
expected_move_points = latest_es * daily_pct_move
em_upper, em_lower = latest_es + expected_move_points, latest_es - expected_move_points

# 3. Top Dashboard Header: Market Vitals
st.markdown("### 📊 Live Market Vitals")
col1, col2, col3, col4 = st.columns(4)
col1.metric(label="ES_F Futures (Live)", value=f"{latest_es:,.2f}")
col2.metric(label="Volatility Index (VIX)", value=f"{live_vix:.2f}")
col3.metric(label="Implied Daily Move (Pts)", value=f"± {expected_move_points:.1f} pts")
col4.metric(label="Implied Daily Range", value=f"{em_lower:.0f} - {em_upper:.0f}")

st.divider()

# 4. Main Chart: Fetch Custom S/R Levels
SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRo0guFofgbGZITI4EGe4aRciVLhlL0zFDmhLLPtxOn1dQ9ErjB3b9PPThlOd7adYmkGv90pv6YiBap/pub?output=csv"
try:
    levels_df = pd.read_csv(SHEET_URL)
except Exception as e:
    st.error("Could not read the Google Sheet. Please double-check the link!")
    st.stop()

# Build Primary ES_F Chart
fig_es = go.Figure(data=[go.Candlestick(x=df_es.index,
                open=df_es['Open'], high=df_es['High'],
                low=df_es['Low'], close=df_es['Close'], name="ES_F")])

# Draw Zones
for index, row in levels_df.iterrows():
    zone_type, bottom, top = row['Type'], row['Bottom'], row['Top']
    fill_color, border_color = ("#00FF00", "#00CC00") if zone_type == "Support" else ("#FF0000", "#CC0000")
    fig_es.add_hrect(y0=bottom, y1=top, line_width=1, line_color=border_color, fillcolor=fill_color, opacity=0.35, annotation_text=zone_type, annotation_position="top left", annotation_font=dict(color="white", size=12))

# Draw Expected Moves
fig_es.add_hline(y=em_upper, line_dash="dash", line_color="#00BFFF", line_width=1.5, annotation_text="Upper Expected Move (+1 SD)", annotation_position="bottom left", annotation_font=dict(color="#00BFFF", size=11))
fig_es.add_hline(y=em_lower, line_dash="dash", line_color="#00BFFF", line_width=1.5, annotation_text="Lower Expected Move (-1 SD)", annotation_position="top left", annotation_font=dict(color="#00BFFF", size=11))

fig_es.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=600, yaxis=dict(side="right"), paper_bgcolor='#111111', plot_bgcolor='#111111', margin=dict(l=10, r=10, t=30, b=10))
st.plotly_chart(fig_es, theme=None, use_container_width=True)

st.divider()

# 5. Macro Liquidity Engine: Side-by-Side Snapshots
st.markdown("### 🌐 Macro Liquidity & Risk Engine")
macro_col1, macro_col2 = st.columns(2)

# Helper function to generate clean, tight line charts for secondary assets
def build_mini_chart(df, title, line_color):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], mode='lines', line=dict(color=line_color, width=2)))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color="white")),
        xaxis_rangeslider_visible=False, template="plotly_dark", height=300,
        paper_bgcolor='#111111', plot_bgcolor='#111111',
        margin=dict(l=10, r=10, t=40, b=10), yaxis=dict(side="right")
    )
    return fig

with macro_col1:
    st.plotly_chart(build_mini_chart(df_nq, "Nasdaq-100 Futures (NQ_F Trend)", "#FF9900"), theme=None, use_container_width=True)

with macro_col2:
    st.plotly_chart(build_mini_chart(df_btc, "Bitcoin / Global Risk (BTC-USD Trend)", "#00FFCC"), theme=None, use_container_width=True)