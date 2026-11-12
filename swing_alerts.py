"""Next Step Trading: swing alerts to Discord.

Runs on a schedule in GitHub Actions (see .github/workflows/swing-alerts.yml). Each run:

  * once a day, freezes the Pullback Watchlist (the week's leaders, as the Weekly Recap ranks them) and each
    name's 21MA as of yesterday's close: the level the intraday rule watches all day;
  * walks every completed hourly bar since the last run:
      - IN THE ZONE  a watchlist name trades down to its 21MA (heads-up),
      - ENTRY        an hourly bar closes back above the 21MA and the full Swing Screener rules pass at that price,
      - T1 / T2 / T3 / STOP on open trades (50 / 25 / 25, stop to breakeven after T1),
      - BACK IN / EXIT for a trade that closed the previous day back under its 21MA: the first hourly bar of the
        next session (9:30 to 10:30 ET) has to close back above it, or the trade is closed at that bar's close;
  * after the close, once a day:
      - CONFIRMED or ON WATCH for each trade entered that day (daily close above or below the 21MA),
      - the Swing Screener's new setups from the whole universe (the close-based method the Shadow Book tracks),
      - a short summary of open trades.

The rules are read straight out of app.py, so the alerts always use the same code as the dashboard. State lives
in a folder (the alert-data branch): state.json for open trades and the day's watchlist, trades.csv for closed
trades and triggers.csv for every watchlist trigger, so results can be measured.

Usage: python swing_alerts.py --data alert-data [--app app.py] [--test]
The Discord webhook comes from the DISCORD_WEBHOOK environment variable.
"""
import argparse
import ast
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")
PLAN = (0.50, 0.25)            # share sold at T1 and T2; the rest at T3 or the stop (same as the Shadow Book)
WATCH_TOP = 6                  # the six biggest gainers, as on the Weekly Recap
EOD_AFTER = (16, 10)           # ET: the daily wrap runs on the first run after this time


# ------------------------------------------------------------------------------------------- rules from app.py

RULE_FUNCS = ["swing_pivots", "watch_state", "pick_targets", "_reject", "screen_setup"]
OPTIONAL_FUNCS = ["_ma_levels"]      # helpers newer versions of app.py use; older ones simply do not have them
RULE_NAMES = ["UNIVERSE_SECTORS", "UNIVERSE", "SCREEN_DEFAULTS", "WATCHLIST"]
OPTIONAL_NAMES = ["SCREEN_RULES_V1"]  # SCREEN_DEFAULTS is built from it in newer versions of app.py


def load_rules(app_path):
    """Pull the screener's functions and lists out of app.py without running the Streamlit page."""
    src = open(app_path, encoding="utf-8").read()
    tree = ast.parse(src)
    funcs, assigns = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in RULE_FUNCS + OPTIONAL_FUNCS and node.name not in funcs:
            funcs[node.name] = node
        elif isinstance(node, ast.Assign):
            for tg in node.targets:
                if isinstance(tg, ast.Name) and tg.id in RULE_NAMES + OPTIONAL_NAMES and tg.id not in assigns:
                    assigns[tg.id] = node
    missing = [n for n in RULE_FUNCS if n not in funcs] + [n for n in RULE_NAMES if n not in assigns]
    if missing:
        raise RuntimeError("app.py no longer defines: " + ", ".join(missing))
    ns = {"pd": pd, "np": np}
    for name in ["UNIVERSE_SECTORS", "UNIVERSE"] + OPTIONAL_NAMES + ["SCREEN_DEFAULTS", "WATCHLIST"]:
        if name not in assigns:
            continue
        exec(compile(ast.Module(body=[assigns[name]], type_ignores=[]), app_path, "exec"), ns)
    for name in OPTIONAL_FUNCS + RULE_FUNCS:
        if name not in funcs:
            continue
        exec(compile(ast.Module(body=[funcs[name]], type_ignores=[]), app_path, "exec"), ns)
    return ns


# ------------------------------------------------------------------------------------------- market data

class YahooData:
    """Daily and hourly bars from Yahoo Finance (the same source as the dashboard)."""

    def __init__(self):
        import yfinance as yf
        self.yf = yf

    def _many(self, tickers, **kw):
        out = {}
        tl = list(dict.fromkeys(tickers))
        for i in range(0, len(tl), 100):
            chunk = tl[i:i + 100]
            data = None
            for attempt in range(3):
                try:
                    data = self.yf.download(tickers=" ".join(chunk), group_by="ticker", progress=False,
                                            threads=False, **kw)
                    break
                except Exception:
                    time.sleep(2 * (attempt + 1))
            if data is None or len(data) == 0:
                continue
            for t in chunk:
                try:
                    df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
                    df = df.dropna(subset=["Close"])
                    if len(df):
                        out[t] = df
                except Exception:
                    continue
        return out

    def daily(self, tickers, days=420):
        start = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
        out = self._many(tickers, start=start, interval="1d", auto_adjust=True)
        for t, df in out.items():
            ix = pd.DatetimeIndex(df.index)
            df.index = (ix.tz_localize(None) if ix.tz is not None else ix).normalize()
        return out

    def hourly(self, tickers):
        out = self._many(tickers, period="5d", interval="60m", auto_adjust=False, prepost=False)
        for t, df in out.items():
            ix = pd.DatetimeIndex(df.index)
            df.index = ix.tz_localize("UTC").tz_convert(ET) if ix.tz is None else ix.tz_convert(ET)
        return out


# ------------------------------------------------------------------------------------------- Discord

class Discord:
    def __init__(self, url, dry=False):
        self.url, self.dry, self.sent = url, dry, []

    def post(self, text):
        if not text:
            return
        chunks, cur = [], ""
        for line in text.split("\n"):           # Discord's limit is 2000 characters a message
            if len(cur) + len(line) + 1 > 1900:
                chunks.append(cur)
                cur = ""
            cur += line + "\n"
        if cur.strip():
            chunks.append(cur)
        for c in chunks:
            self.sent.append(c)
            if self.dry or not self.url:
                print("[discord]", c)
                continue
            import requests
            for attempt in range(3):
                r = requests.post(self.url, json={"content": c, "allowed_mentions": {"parse": []}}, timeout=20)
                if r.status_code == 429:
                    time.sleep(float(r.json().get("retry_after", 2)))
                    continue
                if r.status_code >= 300:
                    print("Discord refused the message:", r.status_code, r.text[:200])
                break
            time.sleep(0.6)


# ------------------------------------------------------------------------------------------- helpers

def px(v):
    return "{:.2f}".format(v)          # no thousands commas, as in the levels posts


def r_mult(entry, stop, legs):
    risk = entry - stop
    if risk <= 0:
        return None
    return sum(sh * (p - entry) for sh, p in legs) / risk


def settled(df, today):
    """Daily bars up to and including yesterday (today's bar is not finished)."""
    return df[df.index < pd.Timestamp(today)]


def week_leaders(R, daily, today):
    """The Weekly Recap's leaders: biggest gain from this week's Monday open to yesterday's close.
    On a Monday (nothing settled yet this week) it is last week's leaders."""
    monday = pd.Timestamp(today) - pd.Timedelta(days=pd.Timestamp(today).weekday())
    if pd.Timestamp(today) == monday:
        monday = monday - pd.Timedelta(days=7)
    chg = {}
    for t in R["WATCHLIST"]:
        df = daily.get(t)
        if df is None:
            continue
        wk = settled(df, today)
        wk = wk[wk.index >= monday]
        if len(wk):
            chg[t] = (float(wk["Close"].iloc[-1]) / float(wk["Open"].iloc[0]) - 1.0) * 100.0
    return sorted(chg.items(), key=lambda kv: -kv[1])[:WATCH_TOP]


def spx_3m(spx_df):
    c = spx_df["Close"].dropna()
    return None if len(c) < 65 else (float(c.iloc[-1]) / float(c.iloc[-64]) - 1.0) * 100.0


def today_frame(daily_df, hourly_today, upto_idx, today):
    """Daily bars with today's bar built from the hourly bars so far, so the screener judges the setup as of now."""
    base = settled(daily_df, today)
    hb = hourly_today.iloc[: upto_idx + 1]
    row = pd.DataFrame({"Open": [float(hb["Open"].iloc[0])], "High": [float(hb["High"].max())],
                        "Low": [float(hb["Low"].min())], "Close": [float(hb["Close"].iloc[-1])],
                        "Volume": [float(hb["Volume"].sum())]}, index=[pd.Timestamp(today)])
    return pd.concat([base[["Open", "High", "Low", "Close", "Volume"]], row])


# ------------------------------------------------------------------------------------------- one run

class Run:
    def __init__(self, R, data, discord, folder, now):
        self.R, self.data, self.dc, self.folder, self.now = R, data, discord, folder, now
        self.today = now.date()
        self.state_path = os.path.join(folder, "state.json")
        self.state = self._load()
        self.msgs = []

    def _load(self):
        try:
            return json.load(open(self.state_path))
        except Exception:
            return {"trades": [], "day": None, "eod_done": None, "processed": {}}

    def _save(self):
        os.makedirs(self.folder, exist_ok=True)
        json.dump(self.state, open(self.state_path, "w"), indent=1, default=str)

    def _log(self, name, row):
        path = os.path.join(self.folder, name)
        os.makedirs(self.folder, exist_ok=True)
        rows, fields = [], list(row.keys())
        if os.path.exists(path):
            with open(path, newline="") as f:
                rd = csv.DictReader(f)
                rows = list(rd)
                old = rd.fieldnames or []
            fields = old + [k for k in fields if k not in old]
        rows.append(row)
        with open(path, "w", newline="") as f:          # rewritten whole, so a new column never misaligns old rows
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r_ in rows:
                w.writerow({k: r_.get(k, "") for k in fields})

    def say(self, text):
        self.msgs.append(text)

    # ---- the day's watchlist, frozen at the first run of the session
    def setup_day(self, daily, spx):
        if self.state.get("day") and self.state["day"].get("date") == str(self.today):
            return
        leaders = week_leaders(self.R, daily, self.today)
        watch = {}
        for t, wk in leaders:
            df = daily.get(t)
            if df is None:
                continue
            ws = self.R["watch_state"](settled(df, self.today), True)
            if not ws or ws["state"] in ("notrend", "notstacked"):
                continue
            watch[t] = dict(ma21=round(ws["m21"], 2), wk=round(wk, 1), label=ws["label"], armed=False,
                            zone_sent=False, entered=False, fail_note=None)
        self.state["day"] = dict(date=str(self.today), watch=watch)
        held = {tr["t"] for tr in self.state["trades"] if tr["status"] != "closed"}
        if watch and (self.now.hour, self.now.minute) < (16, 0):   # a first run after the close is too late to act on
            self.say("**Swing watchlist for " + self.today.strftime("%a %b %d") + "** (long only): an hourly close back "
                     "above the 21MA after a dip to it is the entry.\n"
                     + "\n".join("`%-5s` 21MA %s  (%s, %+.1f%% this week)%s" % (t, px(w["ma21"]), w["label"], w["wk"],
                                 "  · already in a trade" if t in held else "")
                                 for t, w in watch.items()))

    # ---- open trades: stop, targets, breakeven
    def manage(self, tr, bar_ts, b):
        hi, lo, cl = float(b["High"]), float(b["Low"]), float(b["Close"])
        tg = tr["targets"]
        if lo <= tr["stop_now"]:
            tr["legs"].append([1.0 - tr["sold"], tr["stop_now"]])
            tr["sold"] = 1.0
            self.close(tr, bar_ts, "Breakeven stop after T%d" % tr["hits"] if tr["hits"] else "Stopped out")
            return
        while tr["hits"] < len(tg) and hi >= tg[tr["hits"]]:
            lvl = tg[tr["hits"]]
            tr["hits"] += 1
            if tr["hits"] == len(tg):
                tr["legs"].append([1.0 - tr["sold"], lvl])
                tr["sold"] = 1.0
                self.close(tr, bar_ts, "All targets hit")
                return
            share = PLAN[tr["hits"] - 1] if tr["hits"] - 1 < len(PLAN) else 0.0
            tr["legs"].append([share, lvl])
            tr["sold"] += share
            if tr["hits"] == 1:
                tr["stop_now"] = tr["entry"]
            self.say("🎯 **%s T%d hit** at %s: sell %d%%%s." % (tr["t"], tr["hits"], px(lvl), round(share * 100),
                     ", stop to breakeven (%s)" % px(tr["entry"]) if tr["hits"] == 1 else ""))

    def close(self, tr, ts, how, price=None):
        if price is not None:
            tr["legs"].append([1.0 - tr["sold"], price])
            tr["sold"] = 1.0
        tr["status"] = "closed"
        r = r_mult(tr["entry"], tr["stop"], [tuple(x) for x in tr["legs"]])
        pct = sum(sh * (p / tr["entry"] - 1.0) for sh, p in tr["legs"]) * 100.0
        tr.update(exit_ts=str(ts), how=how, r=r, pct=pct)
        icon = "✅" if (r or 0) > 0 else ("⚪" if abs(r or 0) < 0.05 else "🛑")
        self.say("%s **%s closed: %s.** %+.2f%% (%+.2fR) from %s." % (icon, tr["t"], how, pct, r or 0.0, px(tr["entry"])))
        self._log("trades.csv", dict(ticker=tr["t"], source=tr.get("source", "watchlist"), entry_ts=tr["entry_ts"], entry=round(tr["entry"], 2),
                                     stop=round(tr["stop"], 2), t1=tr["targets"][0] if tr["targets"] else "",
                                     exit_ts=str(ts), how=how, hits=tr["hits"], pct=round(pct, 2),
                                     r=round(r, 2) if r is not None else ""))

    # ---- hourly bars
    def hourly(self, daily, hourly, spx):
        open_tr = [tr for tr in self.state["trades"] if tr["status"] != "closed"]
        watch = (self.state.get("day") or {}).get("watch", {})
        names = set(watch) | {tr["t"] for tr in open_tr}
        s3 = spx_3m(settled(spx, self.today)) if spx is not None else None
        for t in sorted(names):
            hdf = hourly.get(t)
            if hdf is None or not len(hdf):
                continue
            hd = hdf[hdf.index.date == self.today]
            done_upto = self.state["processed"].get(t) if self.state["processed"].get(t, "").startswith(str(self.today)) else None
            for i, (ts, b) in enumerate(hd.iterrows()):
                end = ts + pd.Timedelta(minutes=60)
                if end > self.now:
                    break                                            # the bar is still forming
                if done_upto and str(ts) <= done_upto:
                    continue
                self.state["processed"][t] = str(ts)
                first_bar = (ts.hour, ts.minute) == (9, 30)
                for tr in [x for x in self.state["trades"] if x["t"] == t and x["status"] != "closed"]:
                    if tr.get("entry_ts", "") >= str(ts):
                        continue                                     # entered on this bar: start managing next bar
                    self.manage(tr, ts, b)
                    if tr["status"] == "on_watch" and first_bar:
                        if float(b["Close"]) > tr["watch_ma21"]:
                            tr["status"] = "open"
                            self.say("🔁 **%s back in**: the first hour closed at %s, above the 21MA (%s). Trade stays on."
                                     % (t, px(float(b["Close"])), px(tr["watch_ma21"])))
                        else:
                            self.close(tr, end, "Exit: no reclaim in the first hour", float(b["Close"]))
                w = watch.get(t)
                if not w or w["entered"] or any(x["t"] == t and x["status"] != "closed" for x in self.state["trades"]):
                    continue
                lo, cl = float(b["Low"]), float(b["Close"])
                if not w["armed"] and lo <= w["ma21"]:
                    w["armed"] = True
                    if not w["zone_sent"]:
                        w["zone_sent"] = True
                        self.say("👀 **%s in the zone**: traded down to %s, its 21MA (%s). Entry is an hourly close back above it."
                                 % (t, px(lo), px(w["ma21"])))
                        self._log("triggers.csv", dict(date=str(self.today), ticker=t, event="in_zone", ts=str(ts),
                                                       price=round(lo, 2), ma21=w["ma21"], note=""))
                if w["armed"] and cl > w["ma21"]:
                    why = []
                    frame = today_frame(daily[t], hd, i, self.today)
                    res = self.R["screen_setup"](t, frame, True, self.R["SCREEN_DEFAULTS"], s3, why)
                    if res is None:
                        note = why[0] if why else "fails a rule"
                        if w["fail_note"] != note:
                            w["fail_note"] = note
                            self.say("➖ %s closed the hour back above its 21MA at %s, but it is not a trade: %s."
                                     % (t, px(cl), note.lower()))
                            self._log("triggers.csv", dict(date=str(self.today), ticker=t, event="reclaim_rejected",
                                                           ts=str(end), price=round(cl, 2), ma21=w["ma21"], note=note))
                        continue
                    w["entered"] = True
                    tr = dict(t=t, entry=cl, entry_ts=str(ts), entry_day=str(self.today), stop=float(res["stop"]),
                              stop_now=float(res["stop"]), targets=[float(x) for x in res["tg"]], hits=0, sold=0.0,
                              legs=[], status="open_intraday", ma21=w["ma21"])
                    self.state["trades"].append(tr)
                    risk = (cl - tr["stop"]) / cl * 100.0
                    self.say("🟢 **ENTRY %s long at %s** (hourly close %s ET, back above the 21MA %s)\n"
                             "Stop %s (%.1f%% risk) · Targets %s · R:R to T1 %.1f\n"
                             "Plan: sell 50%% at T1 and move the stop to breakeven, 25%% at T2, the rest at T3. "
                             "Today's close has to hold above the 21MA."
                             % (t, px(cl), end.strftime("%H:%M"), px(w["ma21"]), px(tr["stop"]), risk,
                                " / ".join(px(x) for x in tr["targets"]), res["rr"]))
                    self._log("triggers.csv", dict(date=str(self.today), ticker=t, event="entry", ts=str(end),
                                                   price=round(cl, 2), ma21=w["ma21"], note=""))

    # ---- yesterday's screener setups: filled or skipped at today's open
    def open_fills(self, hourly):
        pend = [p for p in self.state.get("pending", []) if p["day"] < str(self.today)]
        if not pend:
            return
        keep = []
        for p in pend:
            h = hourly.get(p["t"])
            hd = h[h.index.date == self.today] if h is not None else None
            if hd is None or not len(hd):
                keep.append(p)                                       # no print yet for this name: try again next run
                continue
            o = float(hd["Open"].iloc[0])
            busy = any(x["t"] == p["t"] and x["status"] != "closed" for x in self.state["trades"])
            if busy:
                self.say("➖ %s opened %s, but it is already an open swing alert trade, so the screener setup is not added."
                         % (p["t"], px(o)))
                continue
            if not (p["lo"] <= o <= p["hi"]):
                side_ = "above" if o > p["hi"] else "below"
                self.say("⏭️ **%s skipped**: opened %s, %s its valid range (%s to %s). No trade." % (p["t"], px(o), side_, px(p["lo"]), px(p["hi"])))
                self._log("triggers.csv", dict(date=str(self.today), ticker=p["t"], event="screener_skipped", ts=str(hd.index[0]),
                                               price=round(o, 2), ma21="", note=side_ + " the range"))
                continue
            ts0 = hd.index[0]
            tr = dict(t=p["t"], entry=o, entry_ts=str(ts0 - pd.Timedelta(minutes=1)), entry_day=str(self.today),
                      stop=p["stop"], stop_now=p["stop"], targets=p["tg"], hits=0, sold=0.0, legs=[],
                      status="open", source="screener")
            self.state["trades"].append(tr)
            risk = (o - p["stop"]) / o * 100.0
            rr = (p["tg"][0] - o) / (o - p["stop"]) if o > p["stop"] else 0.0
            self.say("🟢 **FILLED %s long at the open, %s** (Swing Screener setup from %s's close; valid range %s to %s)\n"
                     "Stop %s (%.1f%% risk) · Targets %s · R:R to T1 from this fill %.1f\n"
                     "Plan: sell 50%% at T1 and move the stop to breakeven, 25%% at T2, the rest at T3."
                     % (p["t"], px(o), pd.Timestamp(p["day"]).strftime("%a"), px(p["lo"]), px(p["hi"]), px(p["stop"]), risk,
                        " / ".join(px(x) for x in p["tg"]), rr))
            self._log("triggers.csv", dict(date=str(self.today), ticker=p["t"], event="screener_filled", ts=str(ts0),
                                           price=round(o, 2), ma21="", note=""))
        self.state["pending"] = [p for p in self.state.get("pending", []) if p["day"] >= str(self.today)] + keep

    # ---- after the close
    def end_of_day(self, daily, spx):
        if self.state.get("eod_done") == str(self.today):
            return
        if (self.now.hour, self.now.minute) < EOD_AFTER:
            return
        last_day = {t: df.index[-1].date() for t, df in daily.items() if len(df)}
        if not any(d == self.today for d in last_day.values()):
            return                                                   # a holiday, or Yahoo has not posted the close yet
        self.state["eod_done"] = str(self.today)
        lines = []
        for tr in [x for x in self.state["trades"] if x["status"] == "open_intraday" and x["entry_day"] == str(self.today)]:
            df = daily.get(tr["t"])
            if df is None or df.index[-1].date() != self.today:
                continue
            c = df["Close"]
            ma = float(c.ewm(span=21, adjust=False).mean().iloc[-1])
            cl = float(c.iloc[-1])
            if cl > ma:
                tr["status"] = "open"
                lines.append("✅ **%s confirmed**: closed %s, above the 21MA (%s). Normal rules from here." % (tr["t"], px(cl), px(ma)))
            else:
                tr["status"] = "on_watch"
                tr["watch_ma21"] = ma
                lines.append("⚠️ **%s on watch**: closed %s, back under the 21MA (%s). It needs the first hour tomorrow "
                             "(9:30 to 10:30 ET) to close back above %s, or it is closed at 10:30." % (tr["t"], px(cl), px(ma), px(ma)))
        # the close-based screener over the whole universe: new today, not already raised yesterday
        s_now = spx_3m(spx) if spx is not None else None
        s_prev = spx_3m(spx.iloc[:-1]) if spx is not None and len(spx) > 1 else None
        new = []
        for t in self.R["UNIVERSE"]:
            df = daily.get(t)
            if df is None or len(df) < 170 or df.index[-1].date() != self.today:
                continue
            try:
                res = self.R["screen_setup"](t, df, True, self.R["SCREEN_DEFAULTS"], s_now)
                if res is None or self.R["screen_setup"](t, df.iloc[:-1], True, self.R["SCREEN_DEFAULTS"], s_prev) is not None:
                    continue
            except Exception:
                continue
            new.append(res)
        self.state["pending"] = [dict(t=r["t"], day=str(self.today), px=float(r["px"]), stop=float(r["stop"]),
                                      tg=[float(x) for x in r["tg"]], lo=float(r["open_lo"]), hi=float(r["open_hi"]),
                                      sec=r["sec"]) for r in new]
        if new:
            lines.append("**New Swing Screener setups at today's close.** Each is taken at tomorrow's open only if the "
                         "open is inside its valid range; you will get a FILLED or SKIPPED alert after the open:")
            for r in sorted(new, key=lambda x: -x["rr"]):
                lines.append("`%-5s` close %s · valid open %s to %s · stop %s · T1 %s · R:R %.1f · %s"
                             % (r["t"], px(r["px"]), px(r["open_lo"]), px(r["open_hi"]), px(r["stop"]),
                                px(r["tg"][0]), r["rr"], r["sec"]))
        open_now = [x for x in self.state["trades"] if x["status"] in ("open", "on_watch")]
        if open_now:
            parts = []
            for tr in open_now:
                df = daily.get(tr["t"])
                if df is None:
                    continue
                last = float(df["Close"].iloc[-1])
                parts.append("%s%s %+.1f%%%s" % (tr["t"], " (screener)" if tr.get("source") == "screener" else "",
                                               (last / tr["entry"] - 1) * 100.0,
                                               ", T%d hit" % tr["hits"] if tr["hits"] else ""))
            lines.append("Open swing alert trades: " + "; ".join(parts) + ".")
        if not lines:
            lines.append("Quiet day: no entries, no new Swing Screener setups and no open trades.")
        if lines:
            self.say("**Swing wrap, " + self.today.strftime("%a %b %d") + "**\n" + "\n".join(lines))

    def go(self):
        day_open = (self.now.hour, self.now.minute) >= (9, 30)
        if self.now.weekday() >= 5 or not day_open:
            return
        trades_t = {tr["t"] for tr in self.state["trades"] if tr["status"] != "closed"}
        trades_t |= {p["t"] for p in self.state.get("pending", [])}
        need = set(self.R["WATCHLIST"]) | trades_t
        eod = (self.now.hour, self.now.minute) >= EOD_AFTER and self.state.get("eod_done") != str(self.today)
        if eod:
            need |= set(self.R["UNIVERSE"])
        hourly = self.data.hourly(sorted(set(self.R["WATCHLIST"]) | trades_t))
        if not any(len(h[h.index.date == self.today]) for h in hourly.values()):
            return                                                   # no session today (a holiday) or no data yet
        daily = self.data.daily(sorted(need) + ["^GSPC"])
        spx = daily.pop("^GSPC", None)
        self.setup_day(daily, spx)
        self.open_fills(hourly)
        self.hourly(daily, hourly, spx)
        self.end_of_day(daily, spx)
        self.state["trades"] = [x for x in self.state["trades"]
                                if x["status"] != "closed" or x.get("exit_ts", "") >= str(self.today - timedelta(days=10))]
        self._save()
        for m in self.msgs:
            self.dc.post(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="alert-data")
    ap.add_argument("--app", default="app.py")
    ap.add_argument("--test", action="store_true", help="send one test message and stop")
    a = ap.parse_args()
    dc = Discord(os.environ.get("DISCORD_WEBHOOK", ""))
    if a.test:
        dc.post("✅ Swing alerts are connected. This channel will get the watchlist, entries, exits and the daily wrap.")
        return
    try:
        R = load_rules(a.app)
        Run(R, YahooData(), dc, a.data, datetime.now(ET)).go()
    except Exception as e:
        dc.post("⚠️ Swing alerts hit a problem and skipped this run: %s: %s" % (type(e).__name__, str(e)[:300]))
        raise


if __name__ == "__main__":
    sys.exit(main())