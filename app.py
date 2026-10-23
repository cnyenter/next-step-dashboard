import streamlit as st
import pandas as pd
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
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

def fetch_many_ohlc(tickers, start_str, adjusted=False):
    """{ticker: DataFrame[Open, High, Low, Close]} of daily bars up to today, in ONE request.

    Raw (unadjusted) prices by default, because stops and targets are set against the prices that
    actually traded. Pass adjusted=True for moving averages and pivots, which want a continuous series.
    """
    if not tickers:
        return {}
    try:
        data = _fetch_with_retry(lambda: yf.download(
            tickers=" ".join(tickers), start=start_str, interval="1d",
            group_by="ticker", auto_adjust=bool(adjusted), progress=False, threads=False))
    except Exception:
        return {}
    if data is None or len(data) == 0:
        return {}
    out = {}
    for t in tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if t not in data.columns.get_level_values(0):
                    continue
                df = data[t]
            else:
                df = data
            cols = [c_ for c_ in ("Open", "High", "Low", "Close", "Volume") if c_ in df.columns]
            df = df[cols].dropna(subset=["Open", "High", "Low", "Close"])
            if len(df):
                out[t] = df
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

def find_reclaim(day_bars, edge, is_support):
    """First 15-minute close back through `edge` after price had traded beyond it.

    A look below and fail only becomes tradable once price comes back. The entry is the close of the
    first bar that finishes back above a support (or back below a resistance) after the sweep, never
    the extreme of the sweep itself, which nobody is filled at. Returns {price, ts} or None.
    """
    if day_bars is None or len(day_bars) == 0:
        return None
    swept = False
    for ts, b in day_bars.iterrows():
        lo, hi, cl = float(b["Low"]), float(b["High"]), float(b["Close"])
        if is_support:
            if not swept and lo < edge:
                swept = True
            if swept and cl >= edge:
                return dict(price=cl, ts=ts)
        else:
            if not swept and hi > edge:
                swept = True
            if swept and cl <= edge:
                return dict(price=cl, ts=ts)
    return None

def swing_pivots(series, lr=5, want_high=True):
    """Local extremes: a bar that is the highest (or lowest) of the bars either side of it."""
    w = lr * 2 + 1
    roll = series.rolling(w, center=True).max() if want_high else series.rolling(w, center=True).min()
    return series[(series == roll)].dropna()

def watch_state(df, is_long, ext_max=6.0, win=5):
    """Where a name stands against the swing screener's setup, and the price that would put it there.

    The screener wants an established trend, a close within ext_max% of the 21MA, and a dip through the
    21MA inside the last `win` sessions that price has since closed back from. A name that is not there yet
    has a specific price at which it would be: the 21MA (a pullback for a long, a bounce for a short), or
    the 50MA when the trend itself is missing. Returns None when there is not enough history.
    """
    if df is None:
        return None
    df = df.dropna(subset=["Close", "High", "Low"])
    if len(df) < 60:
        return None
    c = df["Close"]
    e21 = c.ewm(span=21, adjust=False).mean()
    s50 = c.rolling(50).mean()
    px, m21, m50 = float(c.iloc[-1]), float(e21.iloc[-1]), float(s50.iloc[-1])
    if pd.isna(m50):
        return None
    pc_ = c.shift(1)
    atr = float(pd.concat([df["High"] - df["Low"], (df["High"] - pc_).abs(), (df["Low"] - pc_).abs()], axis=1).max(axis=1).tail(14).mean())
    ext = (px / m21 - 1.0) * 100.0
    w = int(win)
    if is_long:
        in_trend = px > m21 > m50 and px > m50
        fired = bool((df["Low"].iloc[-w:] < e21.iloc[-w:]).any())
    else:
        in_trend = px < m21 < m50 and px < m50
        fired = bool((df["High"].iloc[-w:] > e21.iloc[-w:]).any())
    near = abs(ext) <= ext_max

    trigger = None
    if in_trend and near and fired:
        state, label = "now", "At the 21MA now"
    elif in_trend and not near:
        state, label, trigger = "extended", ("Extended" if is_long else "Extended down"), m21
    elif in_trend:
        state, label, trigger = "coiling", ("Above the 21MA" if is_long else "Below the 21MA"), m21
    elif is_long and px > m50 and m21 > m50:
        state, label, trigger = "below", "Under the 21MA", m21
    elif (not is_long) and px < m50 and m21 < m50:
        state, label, trigger = "below", "Over the 21MA", m21
    elif is_long and px > m50 and m21 <= m50:
        # price is already above both averages; what is missing is the 21MA crossing above the 50MA
        state, label = "notstacked", "Averages not stacked"
    elif (not is_long) and px < m50 and m21 >= m50:
        state, label = "notstacked", "Averages not stacked"
    else:
        state, label = "notrend", ("Not in an uptrend" if is_long else "Not in a downtrend")
        trigger = max(m21, m50) if is_long else min(m21, m50)

    entry = px if trigger is None else trigger
    if is_long:
        cand = sorted(round(float(x), 2) for x in swing_pivots(df["High"].tail(160), 5, True).values if x > entry * 1.005)
        t1 = cand[0] if cand else None
        room = ((t1 / entry - 1.0) * 100.0) if t1 else None
    else:
        cand = sorted((round(float(x), 2) for x in swing_pivots(df["Low"].tail(160), 5, False).values if x < entry * 0.995),
                      reverse=True)
        t1 = cand[0] if cand else None
        room = ((1.0 - t1 / entry) * 100.0) if t1 else None
    away = 0.0 if trigger is None else (trigger / px - 1.0) * 100.0
    return dict(px=px, m21=m21, m50=m50, ext=ext, state=state, label=label, trigger=trigger,
                away=away, t1=t1, room=room, fired=fired, atr=atr)

def _median(v):
    v = sorted(v)
    return v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2.0

def rolling_followthrough(ohlc, idx_df, n_pairs=12, top=6, today=None):
    """Does one week's strength (or weakness) carry into the next? Re-run over many weeks at once.

    Weeks run Monday's open to Friday's close, as on the movers board. For each of the last `n_pairs`
    completed weeks, the `top` biggest gainers and losers are ranked, then followed through the NEXT week
    and compared with the index. Nothing is stored: every week is recomputed from the same daily bars.
    Returns None when there is not enough history.
    """
    td = pd.Timestamp(today) if today is not None else pd.Timestamp.now()
    if td.tzinfo is not None:
        td = td.tz_localize(None)
    td = td.normalize()

    def weekly(df):
        d = df[["Open", "Close"]].dropna().copy()
        ix = d.index
        if getattr(ix, "tz", None) is not None:
            ix = ix.tz_localize(None)
        d.index = pd.DatetimeIndex(ix).normalize()
        if len(d) == 0:
            return pd.Series(dtype=float)
        g = d.resample("W-FRI")
        wk = pd.DataFrame({"open": g["Open"].first(), "close": g["Close"].last()}).dropna()
        last_bar = d.index.max()
        keep = [lab for lab in wk.index if lab <= last_bar or lab < td]   # the Friday has printed or passed
        wk = wk.loc[keep]
        return (wk["close"] / wk["open"] - 1.0) * 100.0

    R = pd.DataFrame({t: weekly(df) for t, df in ohlc.items() if df is not None and len(df)})
    I = weekly(idx_df)
    if R.empty or I.empty:
        return None
    weeks = [w for w in R.index if w in I.index][-(int(n_pairs) + 1):]
    rows = []
    for w0, w1 in zip(weeks[:-1], weeks[1:]):
        r0, r1 = R.loc[w0], R.loc[w1]
        ok = r0.notna() & r1.notna()
        r0, r1 = r0[ok], r1[ok]
        if len(r0) < top * 2:
            continue
        ranked = r0.sort_values(ascending=False)
        lead, lag = list(ranked.index[:top]), list(ranked.index[-top:])
        i1 = float(I.loc[w1])
        L, G = r1[lead], r1[lag]
        rows.append(dict(w0=w0, w1=w1, lead_next=float(L.mean()), lag_next=float(G.mean()), idx_next=i1,
                         lead_beat=int((L > i1).sum()), lag_trail=int((G < i1).sum()), top=top,
                         leaders=lead, laggards=lag))
    if not rows:
        return None
    n = len(rows)
    return dict(rows=rows, n=n, top=top, names=n * top,
                ex_lead=sum(r["lead_next"] - r["idx_next"] for r in rows) / n,
                ex_lag=sum(r["lag_next"] - r["idx_next"] for r in rows) / n,
                lead_beat=sum(r["lead_beat"] for r in rows), lag_trail=sum(r["lag_trail"] for r in rows),
                weeks_lead_beat=sum(1 for r in rows if r["lead_next"] > r["idx_next"]),
                weeks_lag_trail=sum(1 for r in rows if r["lag_next"] < r["idx_next"]),
                med_lead=_median([r["lead_next"] - r["idx_next"] for r in rows]),
                med_lag=_median([r["lag_next"] - r["idx_next"] for r in rows]))

def level_name(is_sup, bottom, top, label=""):
    txt = ("S " if is_sup else "R ")
    txt += "{:,.0f}".format(bottom) if abs(top - bottom) < 0.5 else "{:,.0f} – {:,.0f}".format(bottom, top)
    if label:
        txt += " (" + label + ")"
    return txt

# ==========================================
# SHARED SCREENER RULES
# ==========================================
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

SCREEN_DEFAULTS = dict(min_dv=20.0, max_ext=6.0, pullback_win=5, req_rs=True,
                       min_stop_atr=0.75, min_rr=2.0, max_atr=15.0, pos_cap=15.0)

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


def pick_targets(cands, atr, gap=1.0, n=3, last=None):
    """Take targets nearest-first, skipping any closer than `gap` ATRs to the last one kept.

    Two pivots a few cents apart are one level, not two. Counting them twice makes the
    scale-out plan sell most of the position at essentially the same price. `last` lets a
    second call carry on from targets already chosen.
    """
    out = []
    for x in cands:
        ref = out[-1] if out else last
        if ref is None or abs(x - ref) >= atr * gap:
            out.append(x)
        if len(out) == n:
            break
    return out


def _reject(why, reason):
    """Note which rule ruled a name out, when the caller asked, and return None exactly as before."""
    if why is not None:
        why.append(reason)
    return None

def screen_setup(t, df, want_long, P, spx_3m, why=None):
    """The swing screener's rules for one name as of the last bar of `df`.

    `P` holds the rule settings and `spx_3m` the index's three-month return at that date, so the live
    screener and any replay of it run exactly the same code. Returns a setup dict or None.
    """
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    px = float(c.iloc[-1])
    e21 = c.ewm(span=21, adjust=False).mean()
    s50 = c.rolling(50).mean()
    if pd.isna(s50.iloc[-1]):
        return _reject(why, 'History too short')
    # Average true range: one ATR is roughly one session of movement, so the
    # distance to a target in ATRs is an estimate of how long it would take.
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    if not atr or pd.isna(atr) or atr <= 0:
        return _reject(why, 'No range data')
    m21, m50 = float(e21.iloc[-1]), float(s50.iloc[-1])
    ext = (px / m21 - 1.0) * 100.0
    dv = float((c * v).tail(20).mean()) / 1e6
    if dv < P["min_dv"]:
        return _reject(why, 'Volume too thin')
    rs = (px / float(c.iloc[-64]) - 1.0) * 100.0 if len(c) > 64 else None

    if want_long:
        if not (px > m21 > m50 and px > m50):
            return _reject(why, 'Trend not intact')
        if ext > P["max_ext"]:
            return _reject(why, 'Too far from the 21MA')
        if not bool((df["Low"].iloc[-int(P["pullback_win"]):] < e21.iloc[-int(P["pullback_win"]):]).any()):
            return _reject(why, 'No recent pullback to the 21MA')
        if P["req_rs"] and (rs is None or spx_3m is None or rs <= spx_3m):
            return _reject(why, 'Relative strength vs SPX fails')
        stop = float(l.tail(10).min()) * 0.995
        if stop >= px:
            return _reject(why, 'Stop on the wrong side')
        risk = px - stop
        if risk < atr * P["min_stop_atr"]:
            return _reject(why, 'Stop too tight')
        cand = sorted(set(round(float(x), 2) for x in swing_pivots(h.tail(160), 5, True).values if x > px * 1.005))
        tg = pick_targets(cand, atr)
        if len(tg) < 3:
            lo60, hi60 = float(l.tail(60).min()), float(h.tail(60).max())
            rng = max(hi60 - lo60, px * 0.02)
            fibs = sorted(set(round(lo60 + rng * m, 2) for m in (1.272, 1.618, 2.0) if lo60 + rng * m > px * 1.005))
            if tg:
                fibs = [x for x in fibs if x > tg[-1]]      # only past the last real level
            tg = tg + pick_targets(fibs, atr, n=3 - len(tg), last=tg[-1] if tg else None)
        if not tg:
            return _reject(why, 'No target beyond price')
        rr = (tg[0] - px) / risk
    else:
        if not (px < m21 < m50 and px < m50):
            return _reject(why, 'Trend not intact')
        if abs(ext) > P["max_ext"]:
            return _reject(why, 'Too far from the 21MA')
        if not bool((df["High"].iloc[-int(P["pullback_win"]):] > e21.iloc[-int(P["pullback_win"]):]).any()):
            return _reject(why, 'No recent pullback to the 21MA')
        if P["req_rs"] and (rs is None or spx_3m is None or rs >= spx_3m):
            return _reject(why, 'Relative strength vs SPX fails')
        stop = float(h.tail(10).max()) * 1.005
        if stop <= px:
            return _reject(why, 'Stop on the wrong side')
        risk = stop - px
        if risk < atr * P["min_stop_atr"]:
            return _reject(why, 'Stop too tight')
        cand = sorted(set(round(float(x), 2) for x in swing_pivots(l.tail(160), 5, False).values if x < px * 0.995),
                      reverse=True)
        tg = pick_targets(cand, atr)
        if len(tg) < 3:
            lo60, hi60 = float(l.tail(60).min()), float(h.tail(60).max())
            rng = max(hi60 - lo60, px * 0.02)
            fibs = sorted(set(round(hi60 - rng * m, 2) for m in (1.272, 1.618, 2.0) if 0 < hi60 - rng * m < px * 0.995),
                          reverse=True)
            if tg:
                fibs = [x for x in fibs if x < tg[-1]]      # only past the last real level
            tg = tg + pick_targets(fibs, atr, n=3 - len(tg), last=tg[-1] if tg else None)
        if not tg:
            return _reject(why, 'No target beyond price')
        rr = (px - tg[0]) / risk

    if rr < P["min_rr"]:
        return _reject(why, 'Reward to risk below the minimum')
    atr_t1 = abs(tg[0] - px) / atr
    if atr_t1 > P["max_atr"]:
        return _reject(why, 'Target too far away')
    # Entries here are the last close, but the order goes in at the next open. This is the range of
    # opens at which the setup still clears the two rules that depend on the entry price, with the
    # stop and T1 left where they are: reward at least P["min_rr"] times the risk, and a stop at least
    # P["min_stop_atr"] ATRs away. Outside it the trade is no longer the one that was screened.
    if want_long:
        open_hi = (tg[0] + P["min_rr"] * stop) / (1.0 + P["min_rr"])
        open_lo = stop + atr * P["min_stop_atr"]
    else:
        open_lo = (P["min_rr"] * stop + tg[0]) / (1.0 + P["min_rr"])
        open_hi = stop - atr * P["min_stop_atr"]
    # Flat sizing: every candidate gets the same share of the book, so the risk on each
    # trade is whatever its stop distance makes it. The Risk column shows that figure.
    return dict(t=t, sec=UNIVERSE_SECTORS.get(t, "Other"), px=px, stop=stop, tg=tg, rr=rr,
                ext=ext, rs=rs, atr=atr, atr_t1=atr_t1, stop_atr=risk / atr,
                open_lo=open_lo, open_hi=open_hi,
                raw=float(P["pos_cap"]), size=float(P["pos_cap"]), capped=False)



# ==========================================
# SCREENER SHADOW BOOK
# ==========================================
SHADOW_START = pd.Timestamp("2026-09-25")   # the first screener run: signals from this close onward are tracked
SHADOW_PLAN = (0.50, 0.25)                  # share sold at T1 and at T2; the rest goes at the stop or the last target

def walk_trade(o, h, l, c, k, is_long, entry, stop, tg, plan=SHADOW_PLAN):
    """Manage one trade bar by bar from its entry bar `k`, exactly as the swing rules say.

    The entry fills at the open of bar k, so that whole bar is after the fill. A bar that touches both
    the stop and a target counts as a stop, a level price gapped through fills at the open, the stop
    moves to breakeven once T1 prints, and shares come off at T1 and T2 per `plan` with the remainder
    going at the stop or at the last target. Returns the legs sold and whether the trade is finished.
    """
    n_t = len(tg)
    stop_now, hits, sold, legs = stop, 0, 0.0, []
    for j in range(k, len(c)):
        oj, hj, lj = float(o[j]), float(h[j]), float(l[j])
        if (lj <= stop_now) if is_long else (hj >= stop_now):
            gapped = j > k and ((oj < stop_now) if is_long else (oj > stop_now))
            legs.append((1.0 - sold, oj if gapped else stop_now))
            return dict(done=True, exit_idx=j, legs=legs, hits=hits, sold=1.0, last=float(c[j]),
                        how=("Stopped out" if hits == 0 else "Breakeven after T%d" % hits))
        while hits < n_t and ((hj >= tg[hits]) if is_long else (lj <= tg[hits])):
            lvl = tg[hits]
            gapped = j > k and ((oj > lvl) if is_long else (oj < lvl))
            fill = oj if gapped else lvl
            hits += 1
            if hits == n_t:
                legs.append((1.0 - sold, fill))
                return dict(done=True, exit_idx=j, legs=legs, hits=hits, sold=1.0, last=float(c[j]),
                            how="All targets hit")
            share = plan[hits - 1] if hits - 1 < len(plan) else 0.0
            legs.append((share, fill))
            sold += share
            if hits == 1:
                stop_now = entry
    return dict(done=False, exit_idx=None, legs=legs, hits=hits, sold=sold, last=float(c[-1]),
                how=("Open" if hits == 0 else "Open, T%d hit" % hits))

def trade_result(entry, is_long, legs, last=None, remaining=0.0):
    """One return from every leg sold, with any unsold remainder marked to `last`."""
    ret = (lambda px: (px - entry) / entry * 100.0) if is_long else (lambda px: (entry - px) / entry * 100.0)
    tot = sum(share * ret(px) for share, px in legs)
    if remaining > 0 and last is not None:
        tot += remaining * ret(last)
    return tot

def _signal_prep(df, P, start, min_hist, sidx, s_close, prefilter=True):
    """Per-name arrays and the cheap daily checks that rule most days out before the full rules run.

    Every condition here is necessary for the shared rules to pass, so skipping the days it rejects can never
    drop a real setup (the tests run both ways and compare). Returns None when there is too little history.
    """
    w, tol = int(P["pullback_win"]), 1e-9
    df = df[~df.index.duplicated(keep="last")]
    ix = pd.DatetimeIndex(df.index)
    if ix.tz is not None:
        ix = ix.tz_localize(None)
    ix = ix.normalize()
    n = len(df)
    if n < min_hist + 2:
        return None
    cs = df["Close"]
    e21s, s50s = cs.ewm(span=21, adjust=False).mean(), cs.rolling(50).mean()
    ev, sv, cv = e21s.values, s50s.values, cs.values.astype(float)
    ov, hv, lv = df["Open"].values.astype(float), df["High"].values.astype(float), df["Low"].values.astype(float)
    ar = np.arange(n)
    live = (ar >= min_hist) & (ix >= start)
    if prefilter:
        dvs = ((cs * df["Volume"]).rolling(20).mean() / 1e6).values
        ext = (cv / ev - 1.0) * 100.0
        dip = (df["Low"] < e21s).astype(float).rolling(w).max().fillna(0).values > 0
        poke = (df["High"] > e21s).astype(float).rolling(w).max().fillna(0).values > 0
        # relative strength against the SPX of each day's own date
        if P["req_rs"]:
            jj = sidx.searchsorted(ix, side="right") - 1
            okj = jj >= 63
            sp = np.full(n, np.nan)
            sp[okj] = (s_close[jj[okj]] / s_close[jj[okj] - 63] - 1.0) * 100.0
            rsv = np.full(n, np.nan)
            rsv[63:] = (cv[63:] / cv[:-63] - 1.0) * 100.0
            rs_long = np.isfinite(sp) & np.isfinite(rsv) & (rsv > sp - 1e-9)
            rs_short = np.isfinite(sp) & np.isfinite(rsv) & (rsv < sp + 1e-9)
        else:
            rs_long = rs_short = np.ones(n, bool)
        # stop distance: the swing-low / swing-high stop must sit at least min_stop_atr ATRs from the close
        pcv = np.r_[np.nan, cv[:-1]]
        trv = np.nanmax(np.vstack([hv - lv, np.abs(hv - pcv), np.abs(lv - pcv)]), axis=0)
        atrv = pd.Series(trv).rolling(14).mean().values
        lo10 = pd.Series(lv).rolling(10).min().values * 0.995
        hi10 = pd.Series(hv).rolling(10).max().values * 1.005
        with np.errstate(invalid="ignore"):
            st_long = np.isfinite(lo10) & (atrv > 0) & (lo10 < cv) & (cv - lo10 >= atrv * P["min_stop_atr"] - 1e-9 * cv)
            st_short = np.isfinite(hi10) & (atrv > 0) & (hi10 > cv) & (hi10 - cv >= atrv * P["min_stop_atr"] - 1e-9 * cv)
        base = np.isfinite(sv) & (dvs >= P["min_dv"] - 1e-9) & live
        long_ok = (base & (cv > ev * (1 - tol)) & (ev > sv * (1 - tol)) & (cv > sv * (1 - tol))
                   & (ext <= P["max_ext"] + 1e-9) & dip & rs_long & st_long)
        short_ok = (base & (cv < ev * (1 + tol)) & (ev < sv * (1 + tol)) & (cv < sv * (1 + tol))
                    & (np.abs(ext) <= P["max_ext"] + 1e-9) & poke & rs_short & st_short)
        def t1_ok(i, is_long):
            """Necessary condition only: if a pivot target exists, it must be far enough for the reward-to-risk
            and the ATR distance. With no pivot beyond price the screener falls back to extensions, so pass."""
            win = (hv if is_long else lv)[i - 159: i + 1]
            if len(win) < 160:
                return True
            cen = win[5:155]
            roll = sliding_window_view(win, 11).max(axis=1) if is_long else sliding_window_view(win, 11).min(axis=1)
            if is_long:
                piv = cen[(cen == roll) & (cen > cv[i] * 1.005)]
                if piv.size == 0:
                    return True
                reward, risk = piv.min() - cv[i], cv[i] - lo10[i]
            else:
                piv = cen[(cen == roll) & (cen < cv[i] * 0.995)]
                if piv.size == 0:
                    return True
                reward, risk = cv[i] - piv.max(), hi10[i] - cv[i]
            return reward >= P["min_rr"] * risk - 0.01 and reward / atrv[i] <= P["max_atr"] + 0.01 / atrv[i]
    else:
        long_ok = short_ok = live
        t1_ok = lambda i, is_long: True
    return dict(df=df, ix=ix, n=n, ov=ov, hv=hv, lv=lv, cv=cv, long_ok=long_ok, short_ok=short_ok, t1_ok=t1_ok)

def shadow_replay(data, spx, P, start_date=SHADOW_START, plan=SHADOW_PLAN, min_hist=160, prefilter=True):
    """Replay the swing screener over history and manage every setup it would have raised.

    For each close from `start_date`, the shared rules are run on exactly the data that existed then
    (including that day's three-month SPX return). A setup is entered at the NEXT open, but only if
    that open is still inside the setup's valid range; otherwise it is recorded as skipped. A name
    already in a trade is not entered again. Nothing is stored: it is recomputed from price history.

    data: {ticker: settled daily OHLCV}, spx: frame with Open and Close.
    `min_hist` is the pivot lookback the live screener always has, so a replayed day sees what the screener saw.
    `prefilter` runs the shared rules only on days where cheap necessary conditions hold (trend, extension,
    pullback window, volume, relative strength, stop distance, a pivot target far enough away); turning it off runs them everywhere and exists
    to prove it changes nothing.
    """
    start = pd.Timestamp(start_date).normalize()
    sx = spx[["Open", "Close"]].dropna()
    sidx = pd.DatetimeIndex(sx.index)
    if sidx.tz is not None:
        sidx = sidx.tz_localize(None)
    sidx = sidx.normalize()
    s_open, s_close = sx["Open"].values.astype(float), sx["Close"].values.astype(float)

    def spx_3m_at(date):
        j = int(sidx.searchsorted(date, side="right")) - 1
        return None if j < 63 else (s_close[j] / s_close[j - 63] - 1.0) * 100.0

    def spx_ret(d0, d1):
        j0 = int(sidx.searchsorted(d0, side="left"))
        j1 = int(sidx.searchsorted(d1, side="right")) - 1
        if j0 >= len(sidx) or j1 < j0:
            return None
        return (s_close[j1] / s_open[j0] - 1.0) * 100.0

    w, tol, trades = int(P["pullback_win"]), 1e-9, []
    for t, df in data.items():
        prep = _signal_prep(df, P, start, min_hist, sidx, s_close, prefilter)
        if prep is None:
            continue
        df, ix, n, ov, hv, lv, cv = prep["df"], prep["ix"], prep["n"], prep["ov"], prep["hv"], prep["lv"], prep["cv"]
        long_ok, short_ok, t1_ok = prep["long_ok"], prep["short_ok"], prep["t1_ok"]
        busy_in = busy_out = None
        for i in np.where(long_ok | short_ok)[0]:
            if busy_in is not None and busy_in <= i and (busy_out is None or busy_out > i):
                continue                                   # still in the last trade on this name
            res, is_long = None, None
            for want_long, ok in ((True, long_ok), (False, short_ok)):
                if ok[i] and t1_ok(i, want_long):
                    res = screen_setup(t, df.iloc[: i + 1], want_long, P, spx_3m_at(ix[i]))
                    if res is not None:
                        is_long = want_long
                        break
            if res is None:
                continue
            rec = dict(t=t, sec=res["sec"], side="Long" if is_long else "Short", signal_date=ix[i].date(),
                       signal_px=res["px"], stop=res["stop"], tg=list(res["tg"]), rr_signal=res["rr"],
                       open_lo=res["open_lo"], open_hi=res["open_hi"], last=float(cv[-1]))
            if i == n - 1:
                trades.append(dict(rec, status="Pending"))
                continue
            k = i + 1
            entry = float(ov[k])
            if not (res["open_lo"] <= entry <= res["open_hi"]):
                trades.append(dict(rec, status="Skipped", entry=entry, entry_date=ix[k].date()))
                continue
            wk = walk_trade(ov, hv, lv, cv, k, is_long, entry, res["stop"], res["tg"], plan)
            risk_pct = abs(entry - res["stop"]) / entry * 100.0
            result = trade_result(entry, is_long, wk["legs"], wk["last"], 0.0 if wk["done"] else 1.0 - wk["sold"])
            end_idx = wk["exit_idx"] if wk["done"] else n - 1
            tg0 = res["tg"][0]
            rr_entry = ((tg0 - entry) / (entry - res["stop"])) if is_long else ((entry - tg0) / (res["stop"] - entry))
            trades.append(dict(rec, status="Closed" if wk["done"] else "Open", entry=entry, entry_date=ix[k].date(),
                               exit_date=(ix[wk["exit_idx"]].date() if wk["done"] else None), how=wk["how"],
                               hits=wk["hits"], result=result, risk_pct=risk_pct,
                               r_mult=(result / risk_pct if risk_pct else None), rr=rr_entry,
                               spx=spx_ret(ix[k], ix[end_idx])))
            busy_in, busy_out = k, (wk["exit_idx"] if wk["done"] else None)
    trades.sort(key=lambda x: (x["signal_date"], x["t"]))
    return trades

def walk_setup(hv, lv, i, entry, stop, tg, is_long):
    """Where a setup that fired on bar `i` stands now, from the daily highs and lows after it.

    Entry is that day's close. A bar that touches both the stop and a target counts as a stop, and the stop
    moves to breakeven once T1 prints. Returns (outcome text, targets reached, finished): the same answers the
    screener's original row-by-row walk gave, without building a row object for every bar.
    """
    n, stop_now, hits = len(tg), stop, 0
    for j in range(i + 1, len(hv)):
        hi, lo = hv[j], lv[j]
        if (lo <= stop_now) if is_long else (hi >= stop_now):
            return ("Stopped out", 0, True) if hits == 0 else ("T%d, then breakeven" % hits, hits, True)
        while hits < n and ((hi >= tg[hits]) if is_long else (lo <= tg[hits])):
            hits += 1
            if hits == 1:
                stop_now = entry
        if hits == n:
            return "All targets hit", hits, True
    return ("Open", 0, False) if hits == 0 else ("T%d hit, still open" % hits, hits, False)

def _spx_prep(spx):
    """The index's closes and its three-month return as of any date, for relative strength on that date."""
    sx = spx[["Close"]].dropna() if spx is not None and len(spx) else pd.DataFrame({"Close": []})
    sidx = pd.DatetimeIndex(sx.index)
    if sidx.tz is not None:
        sidx = sidx.tz_localize(None)
    sidx = sidx.normalize()
    s_close = sx["Close"].values.astype(float)

    def spx_3m_at(date):
        j = int(sidx.searchsorted(date, side="right")) - 1
        return None if j < 63 else (s_close[j] / s_close[j - 63] - 1.0) * 100.0
    return sidx, s_close, spx_3m_at

def find_signals(data, spx, P, start_date, want_long=None, min_hist=160, prefilter=True):
    """Every setup the shared rules raise on each close from `start_date`, with no trade logic on top.

    Each day is judged on exactly the data that existed then, including that day's own three-month SPX
    return. `want_long` None looks both ways. Returns dicts with the setup's numbers plus `fired` (the close
    it appeared on) and `i` (that bar's position), oldest first.
    """
    start = pd.Timestamp(start_date).normalize()
    sidx, s_close, spx_3m_at = _spx_prep(spx)
    out = []
    for t, df in data.items():
        prep = _signal_prep(df, P, start, min_hist, sidx, s_close, prefilter)
        if prep is None:
            continue
        df_, ix = prep["df"], prep["ix"]
        for i in np.where(prep["long_ok"] | prep["short_ok"])[0]:
            for is_long, ok in ((True, prep["long_ok"]), (False, prep["short_ok"])):
                if want_long is not None and is_long != want_long:
                    continue
                if ok[i] and prep["t1_ok"](i, is_long):
                    res = screen_setup(t, df_.iloc[: i + 1], is_long, P, spx_3m_at(ix[i]))
                    if res is not None:
                        out.append(dict(res, fired=ix[i].date(), i=int(i)))
                        break
    out.sort(key=lambda x: (x["fired"], x["t"]))
    return out

def shadow_summary(trades):
    """Headline numbers over every entered trade.

    `wins`, `win_rate`, `avg_r` and the like use closed trades only, which skew negative while a book is
    young: stops resolve in days, winners take weeks. The `_all` figures count open trades at their last
    close, and `long` / `short` break the same numbers out by side.
    """
    ent = [x for x in trades if x["status"] in ("Open", "Closed")]
    closed = [x for x in ent if x["status"] == "Closed"]
    n_c = len(closed)
    rs = [x["r_mult"] for x in closed if x.get("r_mult") is not None]
    vs = [x["result"] - x["spx"] for x in closed if x.get("spx") is not None]
    all_r = [x["r_mult"] for x in ent if x.get("r_mult") is not None]
    sides = {}
    for side in ("Long", "Short"):
        sub = [x for x in ent if x["side"] == side]
        sr = [x["r_mult"] for x in sub if x.get("r_mult") is not None]
        sides[side.lower()] = dict(n=len(sub), closed=sum(1 for x in sub if x["status"] == "Closed"),
                                   open=sum(1 for x in sub if x["status"] == "Open"),
                                   avg_r=(sum(sr) / len(sr) if sr else None), total_r=sum(sr))
    return dict(signals=len(trades), entered=len(ent), closed=n_c, open=len(ent) - n_c,
                total_r_all=sum(all_r), avg_r_all=(sum(all_r) / len(all_r) if all_r else None),
                open_profit=sum(1 for x in ent if x["status"] == "Open" and x["result"] > 0),
                long=sides["long"], short=sides["short"],
                skipped=sum(1 for x in trades if x["status"] == "Skipped"),
                pending=sum(1 for x in trades if x["status"] == "Pending"),
                wins=sum(1 for x in closed if x["result"] > 0),
                win_rate=(sum(1 for x in closed if x["result"] > 0) / n_c * 100.0 if n_c else None),
                avg_result=(sum(x["result"] for x in closed) / n_c if n_c else None),
                avg_r=(sum(rs) / len(rs) if rs else None),
                reached_t1=sum(1 for x in ent if x["hits"] >= 1),
                avg_vs_spx=(sum(vs) / len(vs) if vs else None))

def book_match(rec, book, window_days=7):
    """Did the real Swing Book open this ticker within a week after the screener raised it?"""
    if book is None or "Date_Opened_dt" not in book.columns:
        return False
    d0 = pd.Timestamp(rec["signal_date"])
    rows = book[book["Ticker"].astype(str).str.strip().str.upper() == rec["t"]]
    for d in rows["Date_Opened_dt"].dropna():
        if d0 <= pd.Timestamp(d).normalize() <= d0 + pd.Timedelta(days=window_days):
            return True
    return False

def levels_age(levels_date, last_bar_date):
    """How many sessions old the published levels are: 0 when they cover the latest session or one still to come."""
    try:
        n = int(np.busday_count(pd.Timestamp(levels_date).date(), pd.Timestamp(last_bar_date).date()))
        return max(n, 0)
    except Exception:
        return 0

def mark_open(entry, side, partial, live):
    """(blended return, part still unrealised) for an open position, both as % of the whole position.

    `partial` is [(pct_of_position, price)] for scale-outs already taken; the rest is marked to `live`.
    """
    ret = (lambda px: (px - entry) / entry * 100.0) if side == "Long" else (lambda px: (entry - px) / entry * 100.0)
    rem = max(0.0, 100.0 - sum(w for w, _ in partial))
    realised = sum(ret(px) * w / 100.0 for w, px in partial)
    unreal = ret(live) * rem / 100.0
    return realised + unreal, unreal

def _rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    return "rgba(%d,%d,%d,%.2f)" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)

def add_level_layers(fig, zones, price, y_lo, y_hi):
    """Draw every published level on the chart so it reads at a glance, and return what was decided for each.

    zones: [(is_support, bottom, top, label)]. A level is a line when Bottom and Top are the same price and a band
    when they differ. Colour follows where price is NOW: above price red, below green, price inside amber. A level
    that has changed sides since it was published carries an arrow: a published support now above price shows a
    triangle up, a published resistance now below price a triangle down. The two levels nearest price on each side
    are bold. Every level is labelled at the right edge, next to the price axis, with its distance in points.
    """
    span = max(float(y_hi) - float(y_lo), 1.0)
    have_px = price is not None and price == price
    info = []
    for is_sup, bottom, top, lbl in zones:
        dist = None
        if have_px:
            dist = 0.0 if bottom <= price <= top else ((bottom - price) if bottom > price else (top - price))
        info.append(dict(is_sup=is_sup, bottom=bottom, top=top, label=lbl, mid=(bottom + top) / 2.0, dist=dist,
                         line=(top - bottom) < 0.01))
    above = sorted([d for d in info if d["dist"] is not None and d["dist"] > 0], key=lambda d: d["dist"])
    below = sorted([d for d in info if d["dist"] is not None and d["dist"] < 0], key=lambda d: -d["dist"])
    key_ids = {id(d) for d in above[:2] + below[:2] + [d for d in info if d["dist"] == 0.0]}
    key_ids |= {id(d) for d in info if re.search(r"\d+\s*ma|gap", str(d["label"] or ""), re.I)}   # the levels you trade around
    for d in info:
        if d["dist"] is None:
            d["role"] = "support" if d["is_sup"] else "resistance"
        else:
            d["role"] = "resistance" if d["dist"] > 0 else ("support" if d["dist"] < 0 else "inside")
        d["color"] = {"support": GREEN, "resistance": RED, "inside": AMBER}[d["role"]]
        d["flip"] = ""
        if d["dist"] is not None:
            if d["is_sup"] and d["role"] == "resistance":
                d["flip"] = "\u25b2"
            elif (not d["is_sup"]) and d["role"] == "support":
                d["flip"] = "\u25bc"
        d["key"] = id(d) in key_ids
        d["faint"] = not (y_lo <= d["bottom"] <= y_hi or y_lo <= d["top"] <= y_hi)
        d["opacity"] = 0.95 if d["key"] else (0.32 if d["faint"] else 0.6)
        d["width"] = 2.2 if d["key"] else 1.2

    for d in info:
        col = d["color"]
        if d["line"]:
            fig.add_shape(type="line", xref="paper", yref="y", x0=0, x1=1, y0=d["mid"], y1=d["mid"], layer="below",
                          line=dict(color=col, width=d["width"]), opacity=d["opacity"])
        else:
            fig.add_hrect(y0=d["bottom"], y1=d["top"], line_width=0, fillcolor=col,
                          opacity=(0.22 if d["key"] else 0.12), layer="below")
            for edge in (d["bottom"], d["top"]):
                fig.add_shape(type="line", xref="paper", yref="y", x0=0, x1=1, y0=edge, y1=edge, layer="below",
                              line=dict(color=col, width=d["width"] * 0.7), opacity=d["opacity"])

    x_slots, slot, last_y, sep = [0.945, 0.81, 0.675], 0, None, span * 0.04
    for d in sorted(info, key=lambda d: d["mid"]):
        slot = (slot + 1) % len(x_slots) if (last_y is not None and abs(d["mid"] - last_y) < sep) else 0
        last_y, d["slot"] = d["mid"], slot
        txt = level_name(d["is_sup"], d["bottom"], d["top"], d["label"]) + ((" " + d["flip"]) if d["flip"] else "")
        if d["dist"] is not None:
            tail = "inside" if d["dist"] == 0 else ("at price" if abs(d["dist"]) < 0.5 else "{:+.0f}".format(d["dist"]))
            txt += " <span style='color:#c4cfdb'>" + tail + "</span>"
        d["text"] = ("<b>" + txt + "</b>") if d["key"] else txt
        fig.add_annotation(xref="paper", yref="y", x=x_slots[slot], y=d["mid"], xanchor="right",
                           yanchor=("bottom" if d["line"] else "middle"), yshift=(2 if d["line"] else 0), text=d["text"],
                           showarrow=False, font=dict(color="white", size=(13 if d["key"] else 12)),
                           bgcolor=(_rgba(d["color"], 0.85) if d["key"] else "rgba(13,17,23,0.82)"),
                           bordercolor=_rgba(d["color"], 0.85), borderwidth=1, borderpad=3)
    return info

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
        levels_note = "Levels sheet unavailable: zones and ladder hidden."
    if levels_note:
        st.caption(levels_note)
    elif levels_asof is not None:
        st.caption("Levels as published " + levels_asof.strftime("%b %d, %Y"))
        try:
            n_old = levels_age(levels_asof, df_15m.index[-1])
        except Exception:
            n_old = 0
        if n_old >= 1:
            st.markdown("<div class='ns-panel' style='border-left:3px solid " + AMBER + ";'><span style='font-size:13.5px;"
                        "color:#cdd8e4;'><strong>These levels are " + str(n_old) + " session" + ("" if n_old == 1 else "s")
                        + " old.</strong> The latest published set is for " + levels_asof.strftime("%a %b %d")
                        + "; the current session's levels have not been published yet, so read the zones as context, "
                          "not as today's plan.</span></div>", unsafe_allow_html=True)

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

    try:
        px_now = float(latest_price)
    except Exception:
        px_now = None
    add_level_layers(fig, all_zones, px_now, y_lo, y_hi)
    try:       # open on the data, with a margin on the right for the level labels; panning and zooming work as before
        x_first, x_last = df_main.index[0], df_main.index[-1]
        x_range = [x_first, x_last + (x_last - x_first) * 0.18]
    except Exception:
        x_range = None

    for y_val, tag in [(em_upper, "+1 SD"), (em_lower, "-1 SD")]:
        fig.add_hline(y=y_val, line_dash="dash", line_color="#00BFFF", line_width=1.2)
        fig.add_annotation(xref="paper", x=0.995, y=y_val, xanchor="right", yanchor="middle", text=tag,
                           showarrow=False, font=dict(color="white", size=12), bgcolor="#00BFFF", borderpad=3)

    fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_dark", height=620,
                      yaxis=dict(side="right", range=[y_lo, y_hi], fixedrange=False, tickfont=dict(size=13)),
                      xaxis=dict(fixedrange=False, tickfont=dict(size=13), range=x_range),
                      dragmode="pan",
                      paper_bgcolor=BG, plot_bgcolor="#10151f",
                      margin=dict(l=10, r=10, t=34, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                                  bgcolor="rgba(0,0,0,0)", font=dict(size=13)))
    st.plotly_chart(fig, theme=None, use_container_width=True,
                    config={"scrollZoom": True, "displaylogo": False,
                            "modeBarButtonsToRemove": ["select2d", "lasso2d"]})
    st.caption("Scroll or drag to zoom out. Every published level is plotted: red above the last price, green below, bold nearest, "
               "a triangle when it has changed sides, numbers in points from price.")

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
            return "-"
        tot = sum(w for w, _ in legs)
        avg = sum(p * w for w, p in legs) / tot if tot else legs[-1][1]
        return "{:,.2f}".format(avg)

    def _legs_txt(row):
        legs, _ = exit_legs(row)
        n = len([1 for w, _ in legs if w > 0])
        return "-" if n <= 1 else str(n)

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

    # Open positions, marked to the last price. Closed-only figures lean negative while winners are still running,
    # so the open book is shown beside them. Realised scale-outs are already in the monthly figures; `unreal` is
    # only the part not yet sold.
    open_marks = []
    if not open_df.empty:
        try:
            live_s = get_live_prices(list(open_df["Ticker"].unique()))
        except Exception:
            live_s = {}
        for _, orow in open_df.iterrows():
            cur_ = live_s.get(orow["Ticker"])
            entry_ = _num(orow.get("Entry"))
            if cur_ is None or not entry_:
                continue
            blended_, unreal_ = mark_open(entry_, orow.get("Side", "Long"), partial_legs(orow), cur_)
            w_ = _num(orow.get("Weight_Pct")) or (100.0 / float(MAX_OPEN_POSITIONS))
            open_marks.append(dict(t=orow["Ticker"], blended=blended_, unreal=unreal_, weight=w_))

    if closed_df.empty:
        tiles = (
            tile("Book Opened", BOOK_OPENED, "tracked from trade #1")
            + tile("Risk Per Trade", RISK_PER_TRADE, "of allocated capital")
            + tile("Max Open", str(MAX_OPEN_POSITIONS), "positions at a time")
            + tile("Record", "0W / 0L", "every result logged, nothing hidden")
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

        tiles = tile("Closed Trades", str(n), str(len(wins)) + "W / " + str(len(losses)) + "L")
        # A win rate off a handful of trades is noise, not a track record, so say so.
        if n < 5:
            tiles += tile("Win Rate", "%.0f%%" % win_rate, "only %d trade%s, not meaningful yet" % (n, "" if n == 1 else "s"), MUTED)
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
    if open_marks and not closed_df.empty:
        n_o = len(open_marks)
        avg_o = sum(m_["blended"] for m_ in open_marks) / n_o
        prof_o = sum(1 for m_ in open_marks if m_["blended"] > 0)
        tiles += tile("Open Positions", str(n_o), "avg %+.1f%%, %d of %d in profit (marked)" % (avg_o, prof_o, n_o),
                      GREEN if avg_o >= 0 else RED)
        all_res = list(closed_df["Result %"]) + [m_["blended"] for m_ in open_marks]
        avg_all = sum(all_res) / len(all_res)
        tiles += tile("Closed + Open", "%+.1f%%" % avg_all, "avg per trade, %d trades, open ones marked" % len(all_res),
                      GREEN if avg_all >= 0 else RED)
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
            sector = clean_str(row.get("Sector"))
            opened = clean_str(row.get("Date_Opened"))
            thesis = clean_str(row.get("Thesis"))

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

    # ---- Rules check (operator only) ----
    # Replays every open position against daily bars using the stop and targets in the sheet, so a
    # stop or target hit while you were away shows up as a lookup instead of being found weeks later.
    try:
        _code = st.secrets.get("SCREENER_PASSCODE", None)
    except Exception:
        _code = None
    operator = False
    if _code:
        operator = (st.sidebar.text_input("Operator passcode", type="password", key="scr_pass") == _code)

    SCALE_PLAN = (50, 25, 25)     # share sold at T1, T2, T3; used for the "enter this in the sheet" lines

    def rules_check(row, bars):
        """Walk a position forward from the session after it was opened, using its own stop and targets.

        Daily bars hide the order of events inside a day, so a bar that touches both the stop and a
        target counts as a stop, and a level that price gapped through fills at the open rather than at
        its own price. After T1 the stop moves to breakeven, matching the scale-out rule.
        """
        is_long = str(row.get("Side", "Long")) == "Long"
        entry, stop = _num(row.get("Entry")), _num(row.get("Stop"))
        tg = [x for x in (_num(row.get("T1")), _num(row.get("T2")), _num(row.get("T3"))) if x]
        opened = row.get("Date_Opened_dt")
        out = dict(events=[], stopped=None, hits=0, n_targets=len(tg), last=None, asof=None,
                   no_data=False, no_date=False)
        if opened is None or pd.isna(opened):
            out["no_date"] = True
            return out
        if bars is None or len(bars) == 0 or not entry or not stop:
            out["no_data"] = True
            return out
        out["last"], out["asof"] = float(bars["Close"].iloc[-1]), bars.index[-1].date()
        stop_now = stop
        for d, bar in bars.iterrows():
            if d.date() <= opened.date():
                continue                      # the entry day cannot be told apart from the fill itself
            o, hi, lo = float(bar["Open"]), float(bar["High"]), float(bar["Low"])
            if (lo <= stop_now) if is_long else (hi >= stop_now):
                gapped = (o < stop_now) if is_long else (o > stop_now)
                out["stopped"] = dict(date=d.date(), fill=(o if gapped else stop_now), gapped=gapped,
                                      breakeven=out["hits"] >= 1, level=stop_now)
                return out
            while out["hits"] < len(tg) and ((hi >= tg[out["hits"]]) if is_long else (lo <= tg[out["hits"]])):
                lvl = tg[out["hits"]]
                gapped = (o > lvl) if is_long else (o < lvl)
                out["hits"] += 1
                out["events"].append(dict(label="T%d" % out["hits"], date=d.date(), level=lvl,
                                          fill=(o if gapped else lvl), gapped=gapped))
                if out["hits"] == 1:
                    stop_now = entry
        return out

    def needs_action(res, row):
        """Set what the rules say against what the sheet says. Returns severity, lines to enter, result."""
        rec = partial_legs(row)
        n_rec = len(rec)
        lines, final = [], None
        for k, ev in enumerate(res["events"]):
            if k >= n_rec and k < 2:
                lines.append("Exit%d_Date %s, Exit%d_Price %.2f, Exit%d_Pct %d"
                             % (k + 1, ev["date"].isoformat(), k + 1, ev["fill"], k + 1, SCALE_PLAN[k]))
            if k == 2:
                final = ev
        if res["stopped"]:
            s = res["stopped"]
            lines.append("Status CLOSED, Date_Closed %s, Exit_Price %.2f" % (s["date"].isoformat(), s["fill"]))
            final = dict(date=s["date"], fill=s["fill"])
        elif res["n_targets"] and res["hits"] == res["n_targets"]:
            ev = res["events"][-1]
            lines.append("Status CLOSED, Date_Closed %s, Exit_Price %.2f" % (ev["date"].isoformat(), ev["fill"]))
            final = ev

        result = None
        if lines:
            r2 = row.to_dict() if hasattr(row, "to_dict") else dict(row)
            for k, ev in enumerate(res["events"][:2]):
                if k >= n_rec:
                    r2["Exit%d_Price" % (k + 1)], r2["Exit%d_Pct" % (k + 1)] = ev["fill"], SCALE_PLAN[k]
            if final is not None:
                r2["Exit_Price"] = final["fill"]
                result = blended_result(r2)
        sev = "act" if lines else "ok"
        note = ""
        if (not lines) and n_rec > res["hits"]:
            note = "you took a partial before the rules triggered"
        return dict(sev=sev, lines=lines, result=result, note=note)

    @st.cache_data(ttl=900)
    def get_position_bars(tickers, start_str):
        return fetch_many_ohlc(list(tickers), start_str)

    if operator and not open_df.empty:
        st.markdown("<div class='ns-section' style='margin-top:18px;'>🛡️ Rules Check "
                    "<span style='font-size:12px; font-weight:400; text-transform:none; letter-spacing:0; color:" + MUTED
                    + ";'>&nbsp;operator only, not shown to readers</span></div>", unsafe_allow_html=True)
        st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                    "Each open position is replayed against daily bars from the session after it was opened, using the "
                    "stop and targets in your sheet. A bar that touches both the stop and a target counts as a stop, a "
                    "level gapped through fills at the open, and the stop moves to breakeven once T1 prints. It applies "
                    "the Stop in the sheet to the whole period, so if you trail stops by hand, hits before a raise can be "
                    "off. Today's session is included as it stands. Percentages follow the 50 / 25 / 25 plan.</p>",
                    unsafe_allow_html=True)

        starts = open_df["Date_Opened_dt"].dropna() if "Date_Opened_dt" in open_df.columns else pd.Series(dtype="datetime64[ns]")
        if starts.empty:
            st.info("The rules check needs a Date_Opened on each open position.")
        else:
            start_str = (starts.min() - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
            bars_map = get_position_bars(tuple(sorted(open_df["Ticker"].unique())), start_str)
            if not bars_map:
                st.info("Price history could not be loaded right now. Reload in a minute.")
            else:
                body_rows, n_act = "", 0
                for _, prow in open_df.iterrows():
                    res = rules_check(prow, bars_map.get(prow["Ticker"]))
                    side_txt = str(prow.get("Side", ""))
                    opened_txt = prow["Date_Opened_dt"].strftime("%b %d") if pd.notna(prow.get("Date_Opened_dt")) else "?"
                    if res["no_date"] or res["no_data"]:
                        said = "Needs a Date_Opened" if res["no_date"] else "No price data"
                        body_rows += ("<tr><td style='font-weight:700;'>" + prow["Ticker"] + "</td>"
                                      "<td style='color:" + MUTED + ";'>" + side_txt + "</td>"
                                      "<td style='color:" + MUTED + ";'>" + opened_txt + "</td>"
                                      "<td colspan='6' style='color:" + MUTED + ";'>" + said + "</td></tr>")
                        continue
                    act = needs_action(res, prow)
                    n_act += (act["sev"] == "act")

                    parts = []
                    for ev in res["events"]:
                        parts.append("<span style='color:" + GREEN + ";font-weight:600;'>" + ev["label"] + " "
                                     + ev["date"].strftime("%b %d") + ("</span> <span style='color:" + AMBER
                                                                       + ";'>gap, filled at the open</span>" if ev["gapped"] else "</span>"))
                    if res["stopped"]:
                        s = res["stopped"]
                        parts.append("<span style='color:" + RED + ";font-weight:600;'>"
                                     + ("Breakeven stop " if s["breakeven"] else "Stop ") + s["date"].strftime("%b %d")
                                     + "</span>" + (" <span style='color:" + AMBER + ";'>gapped through, filled at the open</span>"
                                                    if s["gapped"] else ""))
                    said = " then ".join(parts) if parts else "<span style='color:" + MUTED + ";'>Nothing triggered</span>"
                    if act["note"]:
                        said += " <span style='color:" + MUTED + ";'>(" + act["note"] + ")</span>"

                    if act["lines"]:
                        todo = "<br>".join(act["lines"])
                    else:
                        todo = "<span style='color:" + GREEN + ";'>Nothing to do</span>"
                    resv = ("<span style='color:" + (GREEN if act["result"] >= 0 else RED) + ";font-weight:600;'>"
                            + "{:+.1f}%".format(act["result"]) + "</span>") if act["result"] is not None else "<span style='color:" + MUTED + ";'>-</span>"
                    last_txt = "{:,.2f}".format(res["last"]) if res["last"] is not None else "-"
                    body_rows += ("<tr style='" + ("background:rgba(240,185,11,.06);" if act["sev"] == "act" else "") + "'>"
                                  "<td style='font-weight:700;'>" + prow["Ticker"] + "</td>"
                                  "<td style='color:" + MUTED + ";'>" + side_txt + "</td>"
                                  "<td style='color:" + MUTED + ";'>" + opened_txt + "</td>"
                                  "<td style='text-align:right;'>" + "{:,.2f}".format(float(prow["Entry"])) + "</td>"
                                  "<td style='text-align:right;color:" + RED + ";'>" + "{:,.2f}".format(float(prow["Stop"])) + "</td>"
                                  "<td style='text-align:right;'>" + last_txt + "</td>"
                                  "<td>" + said + "</td>"
                                  "<td style='font-size:12.5px;'>" + todo + "</td>"
                                  "<td style='text-align:right;'>" + resv + "</td></tr>")

                total = len(open_df)
                if n_act:
                    st.markdown("<div class='ns-panel' style='border-left:3px solid " + AMBER + ";'><span style='font-size:13.5px;"
                                "color:#cdd8e4;'><strong>" + str(n_act) + " of " + str(total) + " open position"
                                + ("" if total == 1 else "s") + " need" + ("s" if n_act == 1 else "")
                                + " updating.</strong> The rules say a stop or target has traded that the sheet does not show "
                                  "yet. The last column is what each trade would be worth if booked as shown.</span></div>",
                                unsafe_allow_html=True)
                else:
                    st.markdown("<div class='ns-panel' style='border-left:3px solid " + GREEN + ";'><span style='font-size:13.5px;"
                                "color:#cdd8e4;'><strong>All " + str(total) + " open positions are on plan.</strong> "
                                "Nothing has traded through a stop or target that the sheet does not already show.</span></div>",
                                unsafe_allow_html=True)
                st.markdown("<style>.rcx{width:100%;border-collapse:collapse;background:#151b26;border:1px solid #232c3d;"
                            "font-size:13.5px;font-family:'IBM Plex Mono',monospace;}"
                            ".rcx th{font-family:'IBM Plex Sans',sans-serif;font-size:11.5px;text-transform:uppercase;"
                            "letter-spacing:0.8px;color:#a8b6c6;padding:10px 12px;border-bottom:1px solid #232c3d;"
                            "font-weight:600;text-align:left;}"
                            ".rcx td{padding:9px 12px;border-bottom:1px solid #1c2434;color:#e6edf3;vertical-align:top;}"
                            "</style><table class='rcx'><tr><th>Ticker</th><th>Side</th><th>Opened</th>"
                            "<th style='text-align:right;'>Entry</th><th style='text-align:right;'>Stop</th>"
                            "<th style='text-align:right;'>Last</th><th>The rules say</th><th>Enter in the sheet</th>"
                            "<th style='text-align:right;'>If booked</th></tr>" + body_rows + "</table>",
                            unsafe_allow_html=True)

    st.divider()

    # ---- Closed trades ----
    st.markdown("### Closed Trades")
    if closed_df.empty:
        st.markdown("<div style='border:1px dashed #444; border-radius:8px; padding:16px; color:" + MUTED + "; font-size:13px;'>"
                    "The book is brand new, so there are no closed trades yet. Every exit is logged here as it happens, winners and losers alike, starting with trade #1. "
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
                    cells += "<td style='text-align:right; color:" + MUTED + ";'>-</td><td style='text-align:right; color:" + MUTED + ";'>-</td>"
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
                       "vs SPX is the difference: the value the trade added over simply owning the index.")

    # ---- Monthly performance vs SPX ----
    st.divider()
    st.markdown("<div class='ns-section'>📈 Performance vs SPX</div>", unsafe_allow_html=True)

    # Every exit is booked in the month it actually happened, so a trade scaled out over two
    # months contributes to both. Only realised exits count: the unsold part of an open
    # position stays out until it is sold.
    def book_leg_contributions(df, default_w):
        """({month: % of book}, number of partial exits that had no usable date)."""
        contribs, undated = {}, 0
        for _, row in df.iterrows():
            status = str(row.get("Status", "")).strip().upper()
            if status not in ("OPEN", "CLOSED"):
                continue
            entry = _num(row.get("Entry"))
            if not entry:
                continue
            side = row.get("Side", "Long")
            w = _num(row.get("Weight_Pct")) or default_w
            closed_dt = row.get("Date_Closed_dt") if status == "CLOSED" else None

            legs = []                                    # (date, % of position sold, price)
            for i in (1, 2):
                px, pc = _num(row.get("Exit%d_Price" % i)), _num(row.get("Exit%d_Pct" % i))
                if px and pc and pc > 0:
                    d = row.get("Exit%d_Date_dt" % i)
                    if d is None or pd.isna(d):
                        d = closed_dt                    # undated partial on a closed trade: use the close
                    legs.append((d, pc, px))
            taken = sum(pc for _, pc, _ in legs)
            final_px = _num(row.get("Exit_Price"))
            if status == "CLOSED" and final_px:
                legs.append((closed_dt, max(0.0, 100.0 - taken), final_px))

            for d, pc, px in legs:
                if d is None or pd.isna(d):
                    undated += 1
                    continue
                m = pd.Timestamp(d).to_period("M")
                contribs[m] = contribs.get(m, 0.0) + leg_return(entry, px, side) * (pc / 100.0) * (w / 100.0)
        return contribs, undated

    default_w = 100.0 / float(MAX_OPEN_POSITIONS)
    for _c in ("Exit1_Date", "Exit2_Date"):
        if _c in book.columns:
            book[_c + "_dt"] = parse_date_col(book[_c])
    leg_contribs, undated_legs = book_leg_contributions(book, default_w)
    book_monthly = pd.Series(leg_contribs, dtype=float).sort_index()

    if not leg_contribs:
        st.markdown("<div style='border:1px dashed #444; border-radius:8px; padding:16px; color:" + MUTED + "; font-size:13.5px;'>"
                    "Monthly performance against SPX appears here once the first exits are booked.</div>", unsafe_allow_html=True)
    else:

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
                                 xaxis=dict(type="category", tickfont=dict(size=12)),
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
                                 xaxis=dict(type="category", tickfont=dict(size=12)),
                                 legend=dict(orientation="h", y=1.0, x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=12)))
                if open_marks:
                    # the unsold part of open positions at their last price, added to the latest month and compounded
                    u_book = sum(m_["weight"] / 100.0 * m_["unreal"] for m_ in open_marks)
                    be_m = 1.0
                    for b_ in book_vals[:-1]:
                        be_m *= 1 + b_ / 100.0
                    be_m *= 1 + (book_vals[-1] + u_book) / 100.0
                    marked_cum = (be_m - 1) * 100.0
                    f2.add_trace(go.Scatter(x=[labels[-1], labels[-1]], y=[book_cum[-1], marked_cum], mode="lines",
                                            showlegend=False, hoverinfo="skip", line=dict(color=AMBER, width=1.5, dash="dot")))
                    f2.add_trace(go.Scatter(x=[labels[-1]], y=[marked_cum], name="Incl. open positions (marked)", mode="markers",
                                            marker=dict(color=AMBER, size=11, symbol="diamond"),
                                            hovertemplate="Incl. open positions, marked: %{y:+.2f}%<extra></extra>"))
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
            method = ("Each exit is booked in the month it happened and weighted at {:.1f}% of the book (an equal slice of {} "
                      "maximum positions), so a trade scaled out over two months contributes to both. A leg's contribution is "
                      "its return, times the share of the position sold, times that weight, not the raw trade percentage. "
                      "Only realised exits count: the unsold part of an open position is left out until it is sold, "
                      "and the amber diamond on the cumulative chart adds that part at its latest price, so it moves with the market. "
                      "Uninvested cash earns nothing. SPX is the price index over the same months."
                      ).format(default_w, MAX_OPEN_POSITIONS)
            if n_months < 3:
                method += " With only {} month{} of exits, treat these figures as a starting point rather than a track record.".format(
                    n_months, "" if n_months == 1 else "s")
            if undated_legs:
                method += (" {} partial exit{} on open trades had no Exit date and {} left out of the chart; "
                           "fill in Exit1_Date or Exit2_Date to include {}.").format(
                    undated_legs, "" if undated_legs == 1 else "s", "was" if undated_legs == 1 else "were",
                    "it" if undated_legs == 1 else "them")
            st.markdown("<div class='ns-panel' style='margin-top:10px; border-left:3px solid " + BLUE + ";'>"
                        "<span style='font-size:13px; color:#cdd8e4;'><strong>How this is calculated.</strong> " + method
                        + "</span></div>", unsafe_allow_html=True)

    # ---- Screener shadow book (operator only) ----
    # Every setup the swing screener raises is tracked as if it had been entered, whether or not it was
    # taken, so the strategy's own performance can be read separately from which trades were actually
    # opened. Nothing is stored: the shared rules are replayed over price history each time.
    if operator:
        st.markdown("<div class='ns-section' style='margin-top:26px;'>🎯 Screener Shadow Book "
                    "<span style='font-size:12px; font-weight:400; text-transform:none; letter-spacing:0; color:" + MUTED
                    + ";'>&nbsp;operator only, not shown to readers</span></div>", unsafe_allow_html=True)
        st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                    "Every setup the Swing Screener has raised since " + SHADOW_START.strftime("%b %d")
                    + ", tracked whether or not you took it. A setup is entered at the <strong>next open</strong>, but only "
                      "if that open is still inside its Valid open range; otherwise it is recorded as skipped. It is then "
                      "managed by the same stop, breakeven-after-T1 and 50 / 25 / 25 rules as the book above, with the "
                      "screener's public rule set (not any settings tried on the Screener page). Positions are unlimited "
                      "and each trade stands alone, so this measures the strategy, not an account.</p>",
                    unsafe_allow_html=True)

        try:
            _now_et = pd.Timestamp.now(tz="US/Eastern")
        except Exception:
            _now_et = pd.Timestamp.now()
        _live = (_now_et.weekday() < 5) and (9 <= _now_et.hour < 16)
        _today = _now_et.normalize().date()
        _end_str = (pd.Timestamp.now().normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

        @st.cache_data(ttl=3600, show_spinner="Replaying the screener since it started...")
        def get_shadow_trades(end_str, live, today_iso):
            data = get_universe_ohlc(tuple(UNIVERSE), end_str)
            if not data:
                return None
            if live:       # today's bar is unfinished, so work from the last completed session, as the screener does
                data = {t_: (d_.iloc[:-1] if len(d_) and d_.index[-1].date().isoformat() == today_iso else d_)
                        for t_, d_ in data.items()}
            sx_ = fetch_history("^SPX", period="2y", interval="1d")
            if sx_ is None or len(sx_) < 70:
                return None
            return shadow_replay(data, sx_, SCREEN_DEFAULTS, SHADOW_START)

        sh_err = None
        try:
            sh_trades = get_shadow_trades(_end_str, _live, _today.isoformat())
        except Exception as e_:
            sh_trades, sh_err = None, e_

        if sh_trades is None:
            if sh_err is not None:      # a code problem must not pose as a data problem
                st.warning("The shadow book could not be built: %s: %s" % (type(sh_err).__name__, str(sh_err)[:160]))
            else:
                st.info("Price history could not be loaded right now. Reload in a minute.")
        elif not sh_trades:
            st.info("The screener has not raised a setup since " + SHADOW_START.strftime("%b %d") + ".")
        else:
            S = shadow_summary(sh_trades)
            for x_ in sh_trades:
                x_["mine"] = book_match(x_, book)
            took = sum(1 for x_ in sh_trades if x_["status"] in ("Open", "Closed") and x_["mine"])

            def _sg(v, d=1):
                return ("{:+." + str(d) + "f}").format(v)
            def _r(v, d=2):
                return "n/a" if v is None else (_sg(v, d) + "R")

            def _col(v):
                return MUTED if v is None else (GREEN if v > 0 else RED)
            n_ent = S["entered"]
            tl = tile("Entered", str(n_ent), "%d closed, %d open" % (S["closed"], S["open"]))
            tl += tile("Average R, all trades", _r(S["avg_r_all"]), "open trades marked to the last close", _col(S["avg_r_all"]))
            tl += tile("Net R, all trades", _r(S["total_r_all"], 1) if n_ent else "n/a", "sum over every entered trade",
                       _col(S["total_r_all"]) if n_ent else MUTED)
            tl += tile("Open, in profit", ("%d of %d" % (S["open_profit"], S["open"])) if S["open"] else "n/a",
                       "marked to the last close", (GREEN if S["open_profit"] * 2 >= S["open"] else AMBER) if S["open"] else MUTED)
            tl += tile("Reached T1", "%d of %d" % (S["reached_t1"], n_ent) if n_ent else "n/a", "of trades entered")
            tl += tile("You took", "%d of %d" % (took, n_ent) if n_ent else "n/a", "also opened in your book")
            st.markdown("<div class='ns-row'>" + tl + "</div>", unsafe_allow_html=True)
            lg, sh = S["long"], S["short"]
            tl2 = tile("Longs", _r(lg["avg_r"]), ("%d trades: %d closed, %d open" % (lg["n"], lg["closed"], lg["open"])) if lg["n"] else "no trades",
                       _col(lg["avg_r"]))
            tl2 += tile("Shorts", _r(sh["avg_r"]), ("%d trades: %d closed, %d open" % (sh["n"], sh["closed"], sh["open"])) if sh["n"] else "no trades",
                        _col(sh["avg_r"]))
            tl2 += tile("Closed only", ("%d of %d won" % (S["wins"], S["closed"])) if S["closed"] else "none yet",
                        ("avg %s, skews negative early" % _r(S["avg_r"])) if S["closed"] else "no trade has closed yet", MUTED)
            tl2 += tile("Vs owning SPX", (_sg(S["avg_vs_spx"]) + " pts") if S["avg_vs_spx"] is not None else "n/a",
                        "avg per closed trade", _col(S["avg_vs_spx"]))
            st.markdown("<div class='ns-row' style='margin-top:8px;'>" + tl2 + "</div>", unsafe_allow_html=True)

            notes = []
            sk = [x_ for x_ in sh_trades if x_["status"] == "Skipped"]
            if sk:
                notes.append("<strong>%d skipped</strong> because the next open was outside the valid range: %s."
                             % (len(sk), ", ".join("%s %s (opened %s)" % (x_["t"], x_["signal_date"].strftime("%b %d"),
                                                                           "{:,.2f}".format(x_["entry"])) for x_ in sk[-8:])
                                + (" and %d earlier" % (len(sk) - 8) if len(sk) > 8 else "")))
            if S["pending"]:
                notes.append("<strong>%d pending</strong>: raised at the latest close, entering at the next open if it is "
                             "still in range." % S["pending"])
            if notes:
                st.markdown("<div class='ns-panel' style='border-left:3px solid " + BLUE + ";'><span style='font-size:13.5px;"
                            "color:#cdd8e4;'>" + " ".join(notes) + "</span></div>", unsafe_allow_html=True)

            shown = [x_ for x_ in sh_trades if x_["status"] in ("Pending", "Open", "Closed")]
            shown.sort(key=lambda x_: (0 if x_["status"] in ("Pending", "Open") else 1, -pd.Timestamp(x_["signal_date"]).toordinal()))
            body_h = ""
            for x_ in shown[:40]:
                is_l = x_["side"] == "Long"
                chip = ("<span style='border:1px solid " + AMBER + ";color:" + AMBER + ";font-size:9.5px;font-weight:600;"
                        "padding:1px 6px;border-radius:4px;margin-left:8px;'>YOURS</span>") if x_["mine"] else ""
                if x_["status"] == "Pending":
                    ent_h = "<span style='color:" + MUTED + ";'>next open</span>"
                    out_h = ("<span style='color:" + MUTED + ";'>Pending: enters between " + "{:,.2f}".format(x_["open_lo"])
                             + " and " + "{:,.2f}".format(x_["open_hi"]) + "</span>")
                    ex_h = res_h = r_h = spx_h = "<span style='color:" + MUTED + ";'>-</span>"
                else:
                    ent_h = "{:,.2f}".format(x_["entry"])
                    how = x_["how"]
                    o_col = RED if how == "Stopped out" else (AMBER if how.startswith("Breakeven") else (GREEN if (x_["hits"] >= 1) else TEXT))
                    out_h = "<span style='color:" + o_col + ";font-weight:600;'>" + how + "</span>"
                    ex_h = x_["exit_date"].strftime("%b %d") if x_["exit_date"] else "<span style='color:" + MUTED + ";'>open</span>"
                    res_h = ("<span style='color:" + (GREEN if x_["result"] >= 0 else RED) + ";font-weight:600;'>" + _sg(x_["result"]) + "%</span>"
                             + ("" if x_["status"] == "Closed" else " <span style='color:" + MUTED + ";font-size:11px;'>marked</span>"))
                    r_h = ("<span style='color:" + MUTED + ";'>" + _sg(x_["r_mult"], 2) + "R</span>") if x_.get("r_mult") is not None else "-"
                    spx_h = ("<span style='color:" + MUTED + ";'>" + _sg(x_["spx"]) + "%</span>") if x_.get("spx") is not None else "-"
                body_h += ("<tr><td style='color:" + MUTED + ";'>" + x_["signal_date"].strftime("%b %d") + "</td>"
                           "<td style='font-weight:700;'>" + x_["t"] + chip + "</td>"
                           "<td style='color:" + (GREEN if is_l else RED) + ";'>" + x_["side"] + "</td>"
                           "<td style='text-align:right;'>" + ent_h + "</td>"
                           "<td style='text-align:right;color:" + RED + ";'>" + "{:,.2f}".format(x_["stop"]) + "</td>"
                           "<td style='text-align:right;color:" + GREEN + ";'>" + "{:,.2f}".format(x_["tg"][0]) + "</td>"
                           "<td>" + out_h + "</td><td>" + ex_h + "</td>"
                           "<td style='text-align:right;'>" + res_h + "</td><td style='text-align:right;'>" + r_h + "</td>"
                           "<td style='text-align:right;'>" + spx_h + "</td></tr>")
            st.markdown("<style>.shx{width:100%;border-collapse:collapse;background:#151b26;border:1px solid #232c3d;font-size:13.5px;"
                        "font-family:'IBM Plex Mono',monospace;margin-top:10px;}.shx th{font-family:'IBM Plex Sans',sans-serif;"
                        "font-size:11.5px;text-transform:uppercase;letter-spacing:0.8px;color:#a8b6c6;padding:10px 12px;"
                        "border-bottom:1px solid #232c3d;font-weight:600;text-align:left;}.shx td{padding:9px 12px;"
                        "border-bottom:1px solid #1c2434;color:#e6edf3;vertical-align:top;}</style>"
                        "<table class='shx'><tr><th>Signal</th><th>Ticker</th><th>Side</th><th style='text-align:right;'>Entry</th>"
                        "<th style='text-align:right;'>Stop</th><th style='text-align:right;'>T1</th><th>Outcome</th><th>Exit</th>"
                        "<th style='text-align:right;'>Result</th><th style='text-align:right;'>R</th>"
                        "<th style='text-align:right;'>SPX</th></tr>" + body_h + "</table>", unsafe_allow_html=True)
            st.markdown("<p style='color:" + MUTED + "; font-size:12.5px; margin:8px 2px 0 2px;'>"
                        + ("Showing the %d most recent of %d trades. " % (40, len(shown)) if len(shown) > 40 else "")
                        + "Hypothetical: it assumes a fill at the open and treats any bar touching both the stop and a target as "
                          "a stop. It is recomputed from price history each time rather than stored, so a borderline signal "
                          "can shift slightly when a dividend adjusts old prices, and with this method the record reaches back "
                          "about six months. R is the result divided by the risk from the actual fill to the stop. "
                          "Closed-only figures skew negative while a book is young, because stops resolve in days and winners "
                          "take weeks; the all-trades figures count open trades at their last close. "
                          "<strong>YOURS</strong> marks a name your book opened within a week of the signal. "
                          "Vs owning SPX is the trade's result minus the index over the same days.</p>", unsafe_allow_html=True)

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

    # Asset registry: add a row here to support another product later.
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
                       + TEXT + ";'>" + A["label"] + "</strong>: how the week traded, measured against the levels published before each open.</p>",
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
                    "<span style='font-size:13.5px; color:#cdd8e4;'><strong>" + range_txt + ": complete.</strong> "
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
                    "<span style='font-size:13.5px; color:#cdd8e4;'><strong>Week to date: " + range_txt + ".</strong> "
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
            st.warning("Yahoo Finance is rate-limiting requests right now. Wait a minute and reload. "
                       "The data is cached for 15 minutes once it loads.")
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
                     "both": ("rgba(240,185,11,.30)", AMBER, "LBAF"), "none": ("#141a24", "#3d4757", "-"),
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
                    # Entry is the reclaim, not the sweep extreme. For a zone, the near edge: the bottom of a
                    # support zone, the top of a resistance zone.
                    day_bars = bars[bars.index.date == d.name.date()]
                    rc = find_reclaim(day_bars, zb if eff_sup else zt, eff_sup)
                    pts = None
                    if rc is not None:
                        pts = (d_close - rc["price"]) if eff_sup else (rc["price"] - d_close)
                    setups.append(dict(day=d.name, zone=(zb, zt), sup=eff_sup, lbl=lbl, extreme=extreme,
                                       reclaim=rc, close=d_close, pts=pts, flipped=flipped))
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

        # Only levels published for the sessions shown belong on this card. A level from another week is not
        # "untested" here; it simply was not part of this week.
        graded_rows = [r for r in graded_rows if any(not (isinstance(c_, str) and c_ == "unpub") for c_ in r["cells"])]
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

        card_html = "" if not shown else ("<style>.rc{width:100%;border-collapse:collapse}"
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
        if lv.empty:
            st.markdown("<div style='border:1px dashed #444; border-radius:8px; padding:16px; color:" + MUTED + "; font-size:13.5px;'>"
                        "No published levels found for <strong>" + A["sheet"] + "</strong> in the levels sheet. "
                        "Add rows with that ticker and the report card will grade them automatically.</div>",
                        unsafe_allow_html=True)
        else:
            st.markdown("<div style='border:1px dashed #444; border-radius:8px; padding:16px; color:" + MUTED + "; font-size:13.5px;'>"
                        "No levels were published for <strong>" + A["sheet"] + "</strong> on these sessions, so there is nothing to "
                        "grade yet. Once that week's levels are in the sheet, the card grades them automatically.</div>",
                        unsafe_allow_html=True)
    if card_html:
        st.markdown("<p class='ns-sub' style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                    "<strong style='color:" + AMBER + ";'>LBAF</strong> = look below and fail, price swept the support and closed back above · "
                    "<strong style='color:" + AMBER + ";'>LAAF</strong> = look above and fail, price poked the resistance and closed back below · "
                    "HELD = support held on the test · REJ = resistance turned it away · BRK = closed through · a dash = price never reached it. "
                    "Graded by the role the level actually had at the open; an asterisk means a gap flipped it from the side it was published on.</p>",
                    unsafe_allow_html=True)
        st.markdown("<div class='ns-panel'>" + card_html + "</div>", unsafe_allow_html=True)
        if setups:
            setups.sort(key=lambda s: (s["pts"] is None, -(s["pts"] or 0.0)))
            rows_html = ""
            for s in setups:
                kind = "Look below and fail" if s["sup"] else "Look above and fail"
                zb, zt = s["zone"]
                zone_txt = "{:,.0f}".format(zb) if abs(zt - zb) < 0.5 else "{:,.0f} – {:,.0f}".format(zb, zt)
                if s["lbl"]:
                    zone_txt += " (" + s["lbl"] + ")"
                if s["reclaim"] is not None:
                    rc_txt = ("{:,.0f}".format(s["reclaim"]["price"]) + " <span style='color:" + MUTED + ";font-size:11.5px;'>"
                              + s["reclaim"]["ts"].strftime("%H:%M") + "</span>")
                else:
                    rc_txt = "-"
                rows_html += ("<tr><td style='color:" + MUTED + ";'>" + s["day"].strftime("%a") + "</td>"
                              "<td style='font-weight:600;color:" + (GREEN if s["sup"] else RED) + ";'>" + kind + "</td>"
                              "<td>" + zone_txt + ("*" if s["flipped"] else "") + "</td>"
                              "<td style='text-align:right;color:" + MUTED + ";'>" + "{:,.0f}".format(s["extreme"]) + "</td>"
                              "<td style='text-align:right;'>" + rc_txt + "</td>"
                              "<td style='text-align:right;'>" + "{:,.0f}".format(s["close"]) + "</td>"
                              "<td style='text-align:right;font-weight:700;color:"
                              + ((GREEN if s["pts"] >= 0 else RED) if s["pts"] is not None else MUTED) + ";'>"
                              + ("{:+,.0f}".format(s["pts"]) if s["pts"] is not None else "-") + "</td></tr>")
            st.markdown("<div class='ns-section' style='margin-top:18px;'>🎯 Setups That Fired</div>",
                        unsafe_allow_html=True)
            st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                        "Every look-below-and-fail and look-above-and-fail at a published level this week. "
                        "<strong>Reclaimed</strong> is the close of the first 15-minute bar back through the level's near edge "
                        "after the sweep (the bottom of a support zone, the top of a resistance zone), which is where an entry "
                        "is realistic. <strong>Points</strong> run from that reclaim to the day's close. The sweep extreme is "
                        "shown only for depth: nobody is filled there.</p>", unsafe_allow_html=True)
            st.markdown("<table class='ns-tbl'><tr>"
                        "<th style='text-align:left;'>Day</th><th style='text-align:left;'>Setup</th>"
                        "<th style='text-align:left;'>Level</th><th style='text-align:right;'>Swept to</th>"
                        "<th style='text-align:right;'>Reclaimed</th>"
                        "<th style='text-align:right;'>Close</th><th style='text-align:right;'>Points</th>"
                        "</tr>" + rows_html + "</table>", unsafe_allow_html=True)

    # ---------- 2. Where the week was fought (time at price) ----------
    st.markdown("<div class='ns-section'>📊 Where The Week Was Fought</div>", unsafe_allow_html=True)
    st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                "Share of 15-minute closes by price bucket: the prices that actually mattered. Builds through the week as bars print.</p>", unsafe_allow_html=True)
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
                "Net points by session block: where the week's trend actually got made.</p>", unsafe_allow_html=True)
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
                bgc, fgc, txt = "#141a24", "#3d4757", "-"
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

    # One download of daily bars feeds both the trend chips on this board and the watchlist below,
    # instead of fetching the same 34 tickers twice.
    @st.cache_data(ttl=1800)
    def get_watch_ohlc(tickers, start_str):
        return fetch_many_ohlc(list(tickers), start_str, adjusted=True)

    _wstart = (pd.Timestamp(e_str) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    try:
        wo = get_watch_ohlc(tuple(WATCHLIST), _wstart)
    except Exception:
        wo = {}
    # The chips describe the selected week, so they use closes only up to that week's end (the end date is
    # exclusive, as it was when this was a separate download). The watchlist below uses the latest data.
    _hist_end = pd.Timestamp(e_str)
    hist = (pd.DataFrame({t_: d_["Close"].loc[d_.index < _hist_end] for t_, d_ in wo.items()}) if wo else None)

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

    # ---------- 6. Pullback watchlist ----------
    @st.cache_data(ttl=1800)
    def get_spx_daily(start_str):
        h = fetch_history("^SPX", start=start_str, interval="1d")
        return h[["Open", "Close"]].dropna() if (h is not None and len(h)) else None

    def _settled(df):
        """Drop today's bar while the session is open, so the levels below do not move with the tape."""
        if df is not None and len(df) and session_open and df.index[-1].date() == today_date:
            return df.iloc[:-1]
        return df

    st.markdown("<div class='ns-section'>🎯 Pullback Watchlist</div>", unsafe_allow_html=True)
    st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                "A strong stock runs away from its 21MA and a weak one runs away from its own, so the week's biggest "
                "movers are rarely at an entry. Each one here has the price that would put it in range: a pullback to the "
                "21MA for a long, a bounce to it for a short, or the 50MA when the trend itself is missing. Set a price "
                "alert at that level. When it is reached and the stock closes back through it, the Swing Screener page "
                "tests it against the full rules (relative strength, reward to risk, stop distance), so a level here is a "
                "place to look, not a signal, and earnings dates are still yours to check. <strong>From here</strong> is the move needed to reach the level. "
                "<strong>Room to T1</strong> is the distance from that level to the nearest pivot, the target the screener "
                "would use. A target marked <strong>too close for 2:1</strong> is under about 1.5 average daily ranges away, so the screener's reward-to-risk rule cannot be met at that level. The 21MA moves every day, so these levels do too.</p>", unsafe_allow_html=True)

    if not mv or not wo:
        st.info("Price history for the watchlist is not available right now.")
    else:
        wl_spx3 = None          # the index's three-month return, which the screener's relative-strength rule needs
        try:
            sp_ = get_spx_daily(_wstart)
            if sp_ is not None:
                sp_ = _settled(sp_)
                if len(sp_) > 65:
                    wl_spx3 = (float(sp_["Close"].iloc[-1]) / float(sp_["Close"].iloc[-64]) - 1.0) * 100.0
        except Exception:
            wl_spx3 = None

        def _wl_rows(items, is_long):
            out = []
            for tkr, wkpct in items:
                if tkr not in wo:
                    continue
                s_ = watch_state(_settled(wo[tkr]), is_long)
                if s_:
                    if s_["state"] == "now" and wl_spx3 is not None:   # in range by price: does the full rule set agree?
                        why_ = []
                        try:
                            ok_ = screen_setup(tkr, _settled(wo[tkr]), is_long, SCREEN_DEFAULTS, wl_spx3, why_)
                        except Exception:       # a price frame problem must never take the page down
                            ok_, why_ = None, ["could not be checked right now"]
                        s_["on_screener"], s_["screen_why"] = ok_ is not None, (why_[0] if why_ else "")
                    out.append((tkr, wkpct, s_))
            out.sort(key=lambda r: (0 if r[2]["state"] == "now" else (3 if r[2]["state"] in ("notrend", "notstacked") else 1),
                                    abs(r[2]["away"])))
            return out

        def _wl_table(title, rows, is_long):
            if not rows:
                return ""
            chip_col = {"now": GREEN, "coiling": BLUE, "extended": AMBER, "below": AMBER, "notrend": MUTED,
                        "notstacked": MUTED}
            body = ""
            for tkr, wkpct, s_ in rows:
                col = chip_col[s_["state"]]
                chip = ("<span style='border:1px solid " + col + ";color:" + col + ";font-size:10.5px;font-weight:600;"
                        "padding:1px 7px;border-radius:4px;white-space:nowrap;'>" + s_["label"] + "</span>")
                trig = "{:,.2f}".format(s_["trigger"]) if s_["trigger"] is not None else ""
                if s_["state"] == "now":
                    if s_.get("on_screener"):
                        todo = "<span style='color:" + GREEN + ";font-weight:600;'>On the Swing Screener now</span>"
                    elif "on_screener" not in s_:
                        todo = "<span style='color:" + MUTED + ";'>In range now: check the Swing Screener</span>"
                    else:
                        todo = ("<span style='color:" + MUTED + ";'>In range by price, but not on the Swing Screener: "
                                + (s_.get("screen_why") or "it fails a rule").lower() + "</span>")
                    away = "<span style='color:" + MUTED + ";'>-</span>"
                elif s_["state"] in ("extended", "coiling"):
                    todo = (("Dip to " if is_long else "Bounce to ") + "<strong>" + trig + "</strong> (21MA), then close back "
                            + ("above" if is_long else "below"))
                    away = "{:+.1f}%".format(s_["away"])
                elif s_["state"] == "below":
                    todo = "Close back " + ("above " if is_long else "below ") + "<strong>" + trig + "</strong> (21MA)"
                    away = "{:+.1f}%".format(s_["away"])
                elif s_["state"] == "notstacked":
                    todo = ("The 21MA (<strong>{:,.2f}</strong>) has to cross " + ("above" if is_long else "below")
                            + " the 50MA (<strong>{:,.2f}</strong>)").format(s_["m21"], s_["m50"])
                    away = "<span style='color:" + MUTED + ";'>-</span>"
                else:
                    todo = ("Reclaim " if is_long else "Lose ") + "<strong>" + trig + "</strong> first"
                    away = "{:+.1f}%".format(s_["away"])
                if s_["t1"] is not None:
                    room = ("{:+.1f}%".format(s_["room"]) if is_long else "{:-.1f}%".format(-s_["room"])) \
                        + " <span style='color:" + MUTED + ";'>to " + "{:,.2f}".format(s_["t1"]) + "</span>"
                    entry_ = s_["px"] if s_["trigger"] is None else s_["trigger"]
                    room_atr = abs(s_["t1"] - entry_) / s_["atr"] if s_.get("atr") else None
                    if room_atr is not None and room_atr < SCREEN_DEFAULTS["min_rr"] * SCREEN_DEFAULTS["min_stop_atr"]:
                        room += ("<div style='color:" + AMBER + ";font-size:11px;margin-top:2px;'>only %.1f ATR away: too close for 2:1</div>"
                                 % room_atr)
                else:
                    room = "<span style='color:" + MUTED + ";'>" + ("Blue sky" if is_long else "No pivot below") + "</span>"
                body += ("<tr><td style='font-weight:700;'>" + tkr + "<div style='color:" + MUTED
                         + ";font-size:11px;font-weight:400;'>" + "{:+.1f}%".format(wkpct) + " last wk</div></td>"
                         "<td>" + chip + "<div style='color:" + MUTED + ";font-size:11px;margin-top:2px;'>"
                         + "{:+.1f}%".format(s_["ext"]) + " vs 21MA</div></td>"
                         "<td>" + todo + "</td>"
                         "<td style='text-align:right;'>" + away + "</td>"
                         "<td style='text-align:right;'>" + room + "</td></tr>")
            return ("<div style='font-size:11.5px;text-transform:uppercase;letter-spacing:0.8px;color:" + MUTED
                    + ";font-weight:600;margin:14px 0 8px 2px;'>" + title + "</div>"
                    "<table class='wl'><tr><th>Ticker</th><th>Where it stands</th><th>Becomes a candidate at</th>"
                    "<th style='text-align:right;'>From here</th><th style='text-align:right;'>Room to T1</th></tr>"
                    + body + "</table>")

        st.markdown("<style>.wl{width:100%;border-collapse:collapse;background:#151b26;border:1px solid #232c3d;"
                    "font-size:13.5px;}.wl th{font-size:11.5px;text-transform:uppercase;letter-spacing:0.8px;color:#a8b6c6;"
                    "padding:10px 12px;border-bottom:1px solid #232c3d;font-weight:600;text-align:left;}"
                    ".wl td{padding:9px 12px;border-bottom:1px solid #1c2434;color:#e6edf3;vertical-align:top;}</style>",
                    unsafe_allow_html=True)
        st.markdown(_wl_table("Longs to watch (the leaders above)", _wl_rows(leaders, True), True)
                    + _wl_table("Shorts to watch (the laggards above)", _wl_rows(laggards, False), False),
                    unsafe_allow_html=True)

    # ---------- 7. Does strength carry? ----------
    ROLL_WEEKS = 12
    st.markdown("<div class='ns-section' style='margin-top:22px;'>🔁 Does Strength Carry?</div>", unsafe_allow_html=True)
    st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                "Each of the last " + str(ROLL_WEEKS) + " weeks, the six biggest gainers and losers on the watchlist were "
                "ranked, then followed through the <em>next</em> week and compared with SPX. One week proves nothing; "
                "a dozen at once is a lean. It answers a practical question: right now, does it pay to buy strength, "
                "or to wait for the pullback?</p>", unsafe_allow_html=True)
    rf = None
    try:
        _spx = get_spx_daily(_wstart)
        if wo and _spx is not None:
            rf = rolling_followthrough({t_: _settled(d_) for t_, d_ in wo.items()}, _settled(_spx),
                                       n_pairs=ROLL_WEEKS, top=6, today=now_et)
    except Exception:
        rf = None

    if rf is None or rf["n"] < 3:
        st.info("Not enough weekly history to test this yet.")
    else:
        lead_pct = rf["lead_beat"] / rf["names"] * 100.0
        lag_pct = rf["lag_trail"] / rf["names"] * 100.0
        tl = tile("Leaders vs SPX", "{:+.1f} pts".format(rf["ex_lead"]), "average over %d weeks, median %+.1f" % (rf["n"], rf["med_lead"]),
                  GREEN if rf["ex_lead"] >= 0 else RED)
        tl += tile("Leaders that beat SPX", "%d of %d" % (rf["lead_beat"], rf["names"]), "%.0f%% the following week" % lead_pct,
                   GREEN if lead_pct >= 50 else RED)
        tl += tile("Laggards vs SPX", "{:+.1f} pts".format(rf["ex_lag"]), "negative means weakness continued",
                   RED if rf["ex_lag"] >= 0 else GREEN)
        tl += tile("Laggards that trailed SPX", "%d of %d" % (rf["lag_trail"], rf["names"]), "%.0f%% the following week" % lag_pct,
                   GREEN if lag_pct >= 50 else RED)
        st.markdown("<div class='ns-row'>" + tl + "</div>", unsafe_allow_html=True)

        # Names within a week move together, so the evidence is the weeks, not the 72 names. A verdict needs the
        # average gap, the typical (median) week and the share of weeks that pointed the same way to all agree.
        n_w, wl_beat, wg_trail = rf["n"], rf["weeks_lead_beat"], rf["weeks_lag_trail"]
        if rf["ex_lead"] <= -0.5 and rf["med_lead"] <= -0.3 and wl_beat <= 0.4 * n_w:
            v_head, v_tail = ("Strength has not carried",
                              " last week's leaders trailed SPX the following week in %d of %d weeks, so buying last week's strength "
                              "has not paid. That favors waiting for the pullback over chasing the breakout." % (n_w - wl_beat, n_w))
        elif rf["ex_lead"] >= 0.5 and rf["med_lead"] >= 0.3 and wl_beat >= 0.6 * n_w:
            v_head, v_tail = ("Strength has carried",
                              " last week's leaders beat SPX the following week in %d of %d weeks, so buying last week's strength "
                              "has paid. That favors buying breakouts over waiting for the pullback." % (wl_beat, n_w))
        else:
            skew = (" (the average of %+.1f is pulled around by a few big weeks)" % rf["ex_lead"]) \
                if abs(rf["ex_lead"] - rf["med_lead"]) >= 0.3 else ""
            v_head, v_tail = ("No clear edge from strength",
                              " last week's leaders beat SPX the following week in %d of %d weeks, and the typical week's gap "
                              "was %+.1f pts%s." % (wl_beat, n_w, rf["med_lead"], skew))
        if rf["ex_lag"] <= -0.5 and rf["med_lag"] <= -0.3 and wg_trail >= 0.6 * n_w:
            v2 = " Weakness has continued: last week's laggards trailed SPX in %d of %d weeks." % (wg_trail, n_w)
        elif rf["ex_lag"] >= 0.5 and rf["med_lag"] >= 0.3 and wg_trail <= 0.4 * n_w:
            v2 = " Weakness has not continued: last week's laggards have tended to bounce."
        else:
            v2 = " Laggards have shown no clear pattern."
        st.markdown("<div class='ns-panel' style='border-left:3px solid " + BLUE + ";'><span style='font-size:13.5px;color:#cdd8e4;'>"
                    "<strong>" + v_head + ":</strong>" + v_tail + v2 + " "
                    + str(rf["n"]) + " weeks of six names is a small sample: read it as a lean for how to approach the screener "
                    "this month, not a rule.</span></div>", unsafe_allow_html=True)

        rows_h = ""
        for r in reversed(rf["rows"]):
            rows_h += ("<tr><td>" + (r["w0"] - pd.Timedelta(days=4)).strftime("%b %d") + " to " + r["w0"].strftime("%b %d")
                       + "</td><td style='color:" + MUTED + ";'>" + (r["w1"] - pd.Timedelta(days=4)).strftime("%b %d")
                       + " to " + r["w1"].strftime("%b %d") + "</td>"
                       "<td style='text-align:right;color:" + (GREEN if r["lead_next"] >= 0 else RED) + ";'>"
                       + "{:+.1f}%".format(r["lead_next"]) + "</td>"
                       "<td style='text-align:right;color:" + (GREEN if r["lag_next"] >= 0 else RED) + ";'>"
                       + "{:+.1f}%".format(r["lag_next"]) + "</td>"
                       "<td style='text-align:right;color:" + MUTED + ";'>" + "{:+.1f}%".format(r["idx_next"]) + "</td>"
                       "<td style='text-align:right;'>" + str(r["lead_beat"]) + " of " + str(r["top"]) + "</td>"
                       "<td style='text-align:right;'>" + str(r["lag_trail"]) + " of " + str(r["top"]) + "</td></tr>")
        st.markdown("<table class='wl'><tr><th>Ranked week</th><th>Followed week</th>"
                    "<th style='text-align:right;'>Leaders</th><th style='text-align:right;'>Laggards</th>"
                    "<th style='text-align:right;'>SPX</th><th style='text-align:right;'>Leaders beat SPX</th>"
                    "<th style='text-align:right;'>Laggards trailed SPX</th></tr>" + rows_h + "</table>",
                    unsafe_allow_html=True)

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
    direction, min_rr, max_ext, min_dv, req_rs = "Long", 2.0, 6.0, 20.0, True
    pos_cap, max_atr, pullback_win = 15.0, 15.0, 5
    lookback_sessions = 20
    min_stop_atr = 0.75
    scale_plan = "50 / 25 / 25"

    if operator:
        c1, c2, c3 = st.columns(3)
        with c1:
            direction = st.radio("Setups", ["Long", "Short"], horizontal=True)
        with c2:
            min_rr = st.number_input("Minimum R:R to T1", 1.0, 5.0, 2.0, 0.25)
            max_ext = st.number_input("Max distance from 21MA (%)", 2.0, 20.0, 6.0, 0.5)
        with c3:
            min_dv = st.number_input("Min average dollar volume ($M)", 1.0, 500.0, 20.0, 5.0)
            req_rs = st.checkbox("Require relative strength vs SPX (3 months)", value=True)
        c4, c5 = st.columns(2)
        with c4:
            pos_cap = st.number_input("Position size per candidate (% of book)", 5.0, 50.0, 15.0, 2.5,
                                      help="Flat for every candidate. The Risk column shows what each stop-out "
                                           "would cost at this size.")
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
        lookback_sessions = st.number_input("Also show setups from the last N sessions", 1, 40, 20, 1,
                                           help="Re-runs the same rules against earlier closes, so a setup that "
                                                "fired while you were away still shows up with the numbers it had "
                                                "on the day. It always reaches back to the screener's first run, so "
                                                "a setup stays until its stop or T1 is touched; this only looks "
                                                "further back than that. 1 means today only.")
        max_atr = st.number_input("Max average daily ranges to T1", 4.0, 60.0, 15.0, 1.0,
                                  help="One ATR is roughly one session of movement, so 15 is about three weeks. "
                                       "A structurally valid target that sits 40 ATRs away is a position trade, not a swing.")
    else:
        st.caption("Candidates are generated from a fixed rule set: 21MA pullback in an established uptrend, "
                   "structural stop, minimum 2:1 reward to the first target, and a target reachable inside a swing timeframe.")

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
    sx = None
    try:
        sx = fetch_history("^SPX", period="6mo", interval="1d")
        if sx is not None and len(sx) > 65:
            spx_3m = (float(sx["Close"].iloc[-1]) / float(sx["Close"].iloc[-64]) - 1.0) * 100.0
    except Exception:
        pass

    pivots = swing_pivots

    def scan(t, df, want_long):
        # the settings on this page, handed to the shared rules
        return screen_setup(t, df, want_long, dict(min_dv=min_dv, max_ext=max_ext, pullback_win=pullback_win,
                                                   req_rs=req_rs, min_stop_atr=min_stop_atr, min_rr=min_rr,
                                                   max_atr=max_atr, pos_cap=pos_cap), spx_3m)

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

    # ---- Setups that are still valid ----
    # Nothing is stored: the shared rules are replayed over recent closes, each day judged on the data that existed
    # then, and every setup is walked forward from the next session. A setup stays valid until its stop or T1 is
    # touched, however long ago it fired.
    prior, valid_rows, resolved_rows, today_set, start_d = {}, [], [], {r["t"] for r in chosen}, None
    if int(lookback_sessions) > 1 and data:
        ref_df = max(data.values(), key=len)
        last_d = ref_df.index[-1].date()
        start_d = ref_df.index[-min(int(lookback_sessions), len(ref_df))].date()
        # A rolling window would drop a setup, or re-date it to a later day of the same pullback, the moment its first
        # day scrolled out. Anchoring at the screener's first run keeps each one where it is until it is resolved.
        start_d = min(start_d, SHADOW_START.date())
        P_now = dict(min_dv=min_dv, max_ext=max_ext, pullback_win=pullback_win, req_rs=req_rs,
                     min_stop_atr=min_stop_atr, min_rr=min_rr, max_atr=max_atr, pos_cap=pos_cap)
        by_t = {}
        for x in find_signals(data, sx, P_now, start_d, want_long=want_long):
            if x["fired"] < last_d:                 # today's close is the main list above
                by_t.setdefault(x["t"], []).append(x)
        for t, lst in by_t.items():
            df_t = data[t][~data[t].index.duplicated(keep="last")]      # the same frame find_signals indexed into
            hv_, lv_, pick = df_t["High"].values.astype(float), df_t["Low"].values.astype(float), None
            for x in lst:                           # oldest first: the first setup that is still alive, else the first one
                x["outcome"], x["hits"], x["done"] = walk_setup(hv_, lv_, x["i"], x["px"], x["stop"], x["tg"], want_long)
                if not x["done"] and pick is None:
                    pick = x
            r = pick if pick is not None else lst[0]
            lc = float(df_t["Close"].iloc[-1])
            r["last"] = lc
            r["now"] = ((lc - r["px"]) / r["px"] * 100.0) if want_long else ((r["px"] - lc) / r["px"] * 100.0)
            if want_long:
                r["rr_now"] = ((r["tg"][0] - lc) / (lc - r["stop"])) if lc > r["stop"] else None
            else:
                r["rr_now"] = ((lc - r["tg"][0]) / (r["stop"] - lc)) if r["stop"] > lc else None
            prior[t] = r
        for t, r in prior.items():
            if t in today_set:
                continue
            if not r["done"]:
                why_ = []
                res_ = screen_setup(t, data[t], want_long, P_now, spx_3m, why_)
                r["why"] = why_[0] if (res_ is None and why_) else "Not on the list"
                valid_rows.append(r)
            else:
                resolved_rows.append(r)
        valid_rows.sort(key=lambda r: (not (r["open_lo"] <= r["last"] <= r["open_hi"] and r["hits"] == 0), -r["fired"].toordinal()))
        resolved_rows.sort(key=lambda r: -r["fired"].toordinal())

    if not chosen:
        if valid_rows:
            st.info("Nothing new qualifies today. %d earlier setup%s still valid: see below." % (
                len(valid_rows), " is" if len(valid_rows) == 1 else "s are"))
        else:
            st.info("Nothing qualifies today. That is a valid result: with no clean pullbacks on offer, "
                    "the honest answer is no trade rather than a lower bar.")
    else:
        rows = ""
        for r in chosen:
            t1, t2, t3 = (list(r["tg"]) + [None, None, None])[:3]
            sz = "{:.1f}%".format(r["size"])
            rk_val = r["size"] * abs(r["px"] - r["stop"]) / r["px"]   # % of book lost if the stop is hit
            _shares = {"50 / 25 / 25": (50, 25, 25), "All out at T1": (100, 0, 0),
                       "Thirds": (33, 33, 34), "50 / 50 at T2": (50, 50, 0)}[scale_plan]
            _plan = " / ".join(str(s) + "%" for s in _shares if s > 0)
            _vo = ("-" if r["held"] else "{:,.2f} to {:,.2f}".format(r["open_lo"], r["open_hi"]))
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
                     "<td style='text-align:right;color:" + MUTED + ";white-space:nowrap;'>" + _vo + "</td>"
                     "<td style='text-align:right;color:" + RED + ";'>" + "{:,.2f}".format(r["stop"]) + "</td>"
                     "<td style='text-align:right;color:" + GREEN + ";'>" + "{:,.2f}".format(t1) + "</td>"
                     "<td style='text-align:right;color:" + MUTED + ";'>" + ("{:,.2f}".format(t2) if t2 else "-") + "</td>"
                     "<td style='text-align:right;color:" + MUTED + ";'>" + ("{:,.2f}".format(t3) if t3 else "-") + "</td>"
                     "<td style='text-align:right;font-weight:700;color:" + AMBER + ";'>" + "{:.1f}".format(r["rr"]) + "</td>"
                     "<td style='text-align:right;'>" + sz + "</td>"
                     "<td style='text-align:right;color:" + MUTED + ";'>" + "{:.2f}%".format(rk_val) + "</td>"
                     "<td style='text-align:right;color:" + MUTED + ";'>" + "{:+.1f}%".format(r["ext"]) + "</td>"
                     "<td style='text-align:right;color:" + (AMBER if r["stop_atr"] < 1.0 else MUTED) + ";'>"
                     + "{:.2f}".format(r["stop_atr"]) + "</td>"
                     "<td style='text-align:right;color:" + (AMBER if r["atr_t1"] > 20 else MUTED) + ";'>"
                     + "{:.0f}".format(r["atr_t1"]) + "</td>"
                     "<td style='text-align:right;color:" + MUTED + ";'>" + _plan + "</td></tr>")
        st.markdown("<table class='ns-tbl'><tr>"
                    "<th style='text-align:left;'>Ticker</th><th style='text-align:left;'>Sector</th>"
                    "<th style='text-align:right;'>Entry</th><th style='text-align:right;'>Valid open</th>"
                    "<th style='text-align:right;'>Stop</th>"
                    "<th style='text-align:right;'>T1</th><th style='text-align:right;'>T2</th>"
                    "<th style='text-align:right;'>T3</th><th style='text-align:right;'>R:R</th>"
                    "<th style='text-align:right;'>Size</th><th style='text-align:right;'>Risk</th>"
                    "<th style='text-align:right;'>vs 21MA</th>"
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
                    "<span style='font-size:13.5px;color:#cdd8e4;'><strong>Size</strong> is a flat share of the book for every candidate, so the risk on each trade depends on how far its stop sits. "
                    "<strong>Risk</strong> is what a stop-out would cost as a percentage of the book: a tight stop risks little but is easier for ordinary noise to take out, so read it alongside Stop ATRs. "
                    "<strong>Stops</strong> "
                    "sit under the swing low that produced the pullback; <strong>targets</strong> are prior pivot highs, "
                    "or fib extensions where price is in blue sky. A row marked <strong>IN BOOK</strong> is a position you "
                    "already hold: its entry and targets are recalculated from the latest close, so they will not "
                    "match your fill. <strong>Valid open</strong> is the range of opening prices at which a new candidate still "
                    "clears the minimum R:R and the minimum stop distance with its stop and T1 left where they are; outside it, the setup is no longer the one screened. <strong>Stop ATRs</strong> is how far the stop sits from entry in average daily ranges: "
                    "under about 1.0 and ordinary noise takes it out, which also flatters the R:R. "
                    "<strong>ATRs to T1</strong> is the distance to the first "
                    "target measured in average daily ranges, which is roughly the number of sessions it would take: "
                    "a $75 target on a volatile $400 stock can be nearer in practice than a $20 target on a quiet one. "
                    "<strong>Scale out</strong> is the share of the position taken at T1, T2 and T3. "
                    "The stop moves to breakeven as soon as T1 fills, which matters more to the result than the "
                    "ratio does.</span></div>", unsafe_allow_html=True)

    # ---- Still valid, and what happened since ----
    if int(lookback_sessions) > 1:
        st.markdown("<div class='ns-section' style='margin-top:22px;'>🗓️ Still Valid, And What Happened Since</div>",
                    unsafe_allow_html=True)
        st.markdown("<p style='color:" + MUTED + "; font-size:14px; margin:-4px 0 12px 2px;'>"
                    "A setup stays <strong>valid</strong> until its stop or T1 is touched, however long ago it fired. This replays "
                    "the screener's rules from its first run on " + (start_d.strftime("%b %d") if start_d else "day one") + ", dates each name by the "
                    "first day its setup appeared, and walks price forward from the next session; the stop moves to breakeven "
                    "once T1 fills. <strong>New entry</strong> asks a different question: would the last close still clear the "
                    "minimum reward to risk and stop distance with the same stop and T1? If not, the setup is live only for "
                    "people already in it. <strong>Last close</strong> is the latest completed session, not a live quote.</p>",
                    unsafe_allow_html=True)
        allp = list(prior.values())
        if allp:
            n_all = len(allp)
            n_stop = sum(1 for r in allp if r["done"] and r["hits"] == 0)
            n_reach = sum(1 for r in allp if r["hits"] >= 1)
            n_open = sum(1 for r in allp if (not r["done"]) and r["hits"] == 0)
            st.markdown("<div class='ns-panel' style='border-left:3px solid " + BLUE + ";'>"
                        "<span style='font-size:13.5px;color:#cdd8e4;'><strong>Of the " + str(n_all)
                        + (" setup" if n_all == 1 else " setups") + " that fired in this window</strong> (including any still on today's list), "
                        + str(n_stop) + " " + ("was" if n_stop == 1 else "were") + " stopped out, "
                        + str(n_reach) + " reached T1 or better, and " + str(n_open) + " "
                        + ("has" if n_open == 1 else "have") + " not yet touched the stop or T1. This is a hypothetical scorecard: it assumes "
                          "entry at that day's close and scores any bar that touches both the stop and a target as a "
                          "stop. A few sessions is a trend to watch, not a verdict.</span></div>",
                        unsafe_allow_html=True)

        def _held_chip(t_):
            if t_ not in open_book:
                return ""
            return ("<span style='border:1px solid " + AMBER + "; color:" + AMBER + "; font-size:9.5px; font-weight:600; "
                    "padding:1px 6px; border-radius:4px; margin-left:8px;'>IN BOOK</span>")

        def _entry_note(r):
            lc, lo_, hi_ = r["last"], r["open_lo"], r["open_hi"]
            if r["hits"] >= 1:
                return "Holders only", MUTED
            if lo_ <= lc <= hi_:
                return (("Valid up to " if want_long else "Valid down to ") + "{:,.2f}".format(hi_ if want_long else lo_)), GREEN
            too_close = (lc < lo_) if want_long else (lc > hi_)
            return ("Too close to its stop" if too_close else "R:R below %.1f from here" % min_rr), AMBER

        if valid_rows:
            rows_v = ""
            for r in valid_rows[:15]:
                note, ncol = _entry_note(r)
                rr_txt = "{:.1f}".format(r["rr_now"]) if r["rr_now"] is not None else "-"
                rows_v += ("<tr><td style='font-weight:700;'>" + r["t"] + _held_chip(r["t"]) + "</td>"
                           "<td style='color:" + MUTED + ";'>" + r["sec"] + "</td>"
                           "<td style='color:" + MUTED + ";'>" + r["fired"].strftime("%a %b %d") + "</td>"
                           "<td style='text-align:right;'>" + "{:,.2f}".format(r["px"]) + "</td>"
                           "<td style='text-align:right;color:" + RED + ";'>" + "{:,.2f}".format(r["stop"]) + "</td>"
                           "<td style='text-align:right;color:" + GREEN + ";'>" + "{:,.2f}".format(r["tg"][0]) + "</td>"
                           "<td style='text-align:right;'>" + "{:,.2f}".format(r["last"]) + "</td>"
                           "<td style='text-align:right;font-weight:600;color:" + (GREEN if r["now"] >= 0 else RED) + ";'>"
                           + "{:+.1f}%".format(r["now"]) + "</td>"
                           "<td style='text-align:right;font-weight:700;color:" + AMBER + ";'>" + rr_txt + "</td>"
                           "<td style='color:" + ncol + ";font-weight:600;'>" + note + "</td>"
                           "<td style='color:" + MUTED + ";'>" + r["why"] + "</td></tr>")
            st.markdown("<div style='font-size:11.5px;text-transform:uppercase;letter-spacing:1px;color:" + GREEN + ";margin:10px 0 4px 2px;'>"
                        "Still valid</div><table class='ns-tbl'><tr>"
                        "<th style='text-align:left;'>Ticker</th><th style='text-align:left;'>Sector</th>"
                        "<th style='text-align:left;'>Fired</th><th style='text-align:right;'>Entry that day</th>"
                        "<th style='text-align:right;'>Stop</th><th style='text-align:right;'>T1</th>"
                        "<th style='text-align:right;'>Last close</th><th style='text-align:right;'>Now</th>"
                        "<th style='text-align:right;'>R:R from here</th><th style='text-align:left;'>New entry</th>"
                        "<th style='text-align:left;'>Left today's list because</th>"
                        "</tr>" + rows_v + "</table>", unsafe_allow_html=True)
        else:
            st.info("No earlier setup is still valid: every one has either been stopped out, reached T1, or is on today's list.")

        if resolved_rows:
            rows_r = ""
            for r in resolved_rows[:12]:
                o_col = RED if r["hits"] == 0 else (GREEN if r["outcome"] == "All targets hit" else AMBER)
                rows_r += ("<tr><td style='font-weight:700;'>" + r["t"] + _held_chip(r["t"]) + "</td>"
                           "<td style='color:" + MUTED + ";'>" + r["sec"] + "</td>"
                           "<td style='color:" + MUTED + ";'>" + r["fired"].strftime("%a %b %d") + "</td>"
                           "<td style='text-align:right;'>" + "{:,.2f}".format(r["px"]) + "</td>"
                           "<td style='text-align:right;color:" + RED + ";'>" + "{:,.2f}".format(r["stop"]) + "</td>"
                           "<td style='text-align:right;color:" + GREEN + ";'>" + "{:,.2f}".format(r["tg"][0]) + "</td>"
                           "<td style='color:" + o_col + ";font-weight:600;'>" + r["outcome"] + "</td>"
                           "<td style='text-align:right;'>" + "{:,.2f}".format(r["last"]) + "</td>"
                           "<td style='text-align:right;font-weight:600;color:" + (GREEN if r["now"] >= 0 else RED) + ";'>"
                           + "{:+.1f}%".format(r["now"]) + "</td></tr>")
            st.markdown("<div style='font-size:11.5px;text-transform:uppercase;letter-spacing:1px;color:" + MUTED + ";margin:16px 0 4px 2px;'>"
                        "Resolved</div><table class='ns-tbl'><tr>"
                        "<th style='text-align:left;'>Ticker</th><th style='text-align:left;'>Sector</th>"
                        "<th style='text-align:left;'>Fired</th><th style='text-align:right;'>Entry that day</th>"
                        "<th style='text-align:right;'>Stop</th><th style='text-align:right;'>T1</th>"
                        "<th style='text-align:left;'>Outcome</th><th style='text-align:right;'>Last close</th>"
                        "<th style='text-align:right;'>Now</th></tr>" + rows_r + "</table>", unsafe_allow_html=True)

    st.markdown("<p style='color:" + MUTED + "; font-size:11.5px; text-align:center; margin-top:16px;'>"
                "A screen is a starting point, not a trade list. Check earnings dates before entering anything. "
                "This is not trading advice. This is purely for information/education.</p>", unsafe_allow_html=True)