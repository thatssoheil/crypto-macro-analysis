#!/usr/bin/env python3
"""BULL-SIGNAL LEAD-TIME STUDY (2026-10-09).

Question: across BTC's cycle bottoms, which indicator flips BULLISH first -
and what does that speed cost in whipsaws? Requested by the owner ("exercise
different indicators on the btc chart... which has historically signaled
bullmarket sooner... look into supertrend as starter"), daily AND weekly.

Method (house conventions):
- Data: committed Bitstamp BTC daily OHLCV (2011-08+) from data/macro_dataset.
- All signals evaluate on the bar CLOSE (daily close / weekly close, W-SUN);
  no intraday, no lookahead. Weekly bars are resampled from the daily series.
- States are NaN during indicator warmup (a comparison against an undefined
  average is NOT a bear reading) - a flip counts only as an observed 0 -> 1
  transition, so first-valid-bar artifacts cannot fake a signal.
- Cycle bottoms are detected MECHANICALLY, not hand-picked: a day whose LOW is
  the minimum of the surrounding +/-365 days and from which the close doubles
  (>=2x) within 730 days. Clusters (gaps <= 45d) collapse to their lowest day.
  The 2020-03-13 crash low FAILS this rule (the 2019-03-14 grind low of 3,775
  undercuts its 3,850 by $75) and is added as a labelled supplementary bottom
  ('20*) - including it is a deliberate V-recovery stress test.
- Per variant x bottom: first bullish flip at/after the bottom -> delay (days),
  % above the bottom close at the flip.
- Quality axes (the point of the study):
  * whipsaw = share of bullish flips reversed (bearish flip) within 30 days;
  * pre-bottom flips = bullish flips in the 365 days BEFORE each bottom
    (crying wolf into a falling knife);
  * fwd1y = median 1-calendar-year forward return after a flip vs the
    unconditional baseline (directional sanity check: lead-time speed never
    stands in for a directional check).
- Supertrend implementation is the canonical one from the ZEC study
  (~/hermes-dump/zec-supertrend-20261007/analysis.py) - copied verbatim, so
  flips are comparable with that evidence base.
- Forward returns: 365 bars on daily, 52 bars on weekly (both = 1 calendar year).

STATELESS: prints everything to stdout. --outdir additionally writes result
CSVs for charting (explicit opt-in; the repo itself stores no results).

Run: ./.venv/bin/python research/bull_signal_leadtime.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "macro_dataset" / "btcusd_daily_bitstamp.csv"

WHIP_WIN = 30      # days: a bullish flip reversed within this = whipsaw
MAX_DELAY = 730    # days: window after a bottom to find the first flip
FWD_DAILY = 365    # bars ~ 1 calendar year
FWD_WEEKLY = 52    # bars = 1 calendar year


# ---------------------------------------------------------------- primitives --
def atr_rma(df, n):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def supertrend(df, n=10, mult=3.0):
    """Canonical Supertrend (TradingView KivancOzbilgic logic) - verbatim from
    the ZEC study so flips match that evidence base."""
    hl2 = (df["high"] + df["low"]) / 2.0
    a = atr_rma(df, n)
    up = hl2 + mult * a
    lo = hl2 - mult * a
    fu, fl, d = {}, {}, {}
    start = a.first_valid_index()
    idx = df.index
    i0 = idx.get_loc(start)
    fu[idx[i0]], fl[idx[i0]], d[idx[i0]] = up.iloc[i0], lo.iloc[i0], 1.0
    for i in range(i0 + 1, len(df)):
        c_prev = df["close"].iloc[i - 1]
        fu[idx[i]] = min(up.iloc[i], fu[idx[i - 1]]) if c_prev <= fu[idx[i - 1]] else up.iloc[i]
        fl[idx[i]] = max(lo.iloc[i], fl[idx[i - 1]]) if c_prev >= fl[idx[i - 1]] else lo.iloc[i]
        c = df["close"].iloc[i]
        if c > fu[idx[i - 1]]:
            d[idx[i]] = 1.0
        elif c < fl[idx[i - 1]]:
            d[idx[i]] = -1.0
        else:
            d[idx[i]] = d[idx[i - 1]]
    fu_s = pd.Series(fu)
    fl_s = pd.Series(fl)
    d_s = pd.Series(d)
    st = pd.Series(np.where(d_s == 1, fl_s, fu_s), index=d_s.index)
    return pd.DataFrame({"dir": d_s, "st": st, "atr": a, "close": df["close"]})


def rsi_wilder(close, n=14):
    d = close.diff()
    u = d.clip(lower=0.0).to_numpy()
    v = (-d).clip(lower=0.0).to_numpy()
    out = np.full(len(close), np.nan)
    if len(close) <= n:
        return pd.Series(out, index=close.index)
    au = u[1:n + 1].mean()
    ad = v[1:n + 1].mean()
    out[n] = 100.0 if ad == 0 else 100.0 - 100.0 / (1.0 + au / ad)
    for i in range(n + 1, len(close)):
        au = (au * (n - 1) + u[i]) / n
        ad = (ad * (n - 1) + v[i]) / n
        out[i] = 100.0 if ad == 0 else 100.0 - 100.0 / (1.0 + au / ad)
    return pd.Series(out, index=close.index)


def psar_dir(df, af=0.02, step=0.02, maxaf=0.2):
    """Classic Parabolic SAR; +1 = long state."""
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    n = len(df)
    d = np.ones(n)
    sar = np.empty(n)
    ep = np.empty(n)
    afs = np.empty(n)
    d[0], sar[0], ep[0], afs[0] = 1.0, l[0], h[0], af
    for i in range(1, n):
        if d[i - 1] == 1:
            s = sar[i - 1] + afs[i - 1] * (ep[i - 1] - sar[i - 1])
            s = min(s, l[i - 1], l[i - 2] if i >= 2 else l[i - 1])
            if l[i] < s:
                d[i], sar[i], ep[i], afs[i] = -1.0, ep[i - 1], l[i], af
            else:
                d[i] = 1.0
                if h[i] > ep[i - 1]:
                    ep[i] = h[i]
                    afs[i] = min(afs[i - 1] + step, maxaf)
                else:
                    ep[i] = ep[i - 1]
                    afs[i] = afs[i - 1]
                sar[i] = s
        else:
            s = sar[i - 1] + afs[i - 1] * (ep[i - 1] - sar[i - 1])
            s = max(s, h[i - 1], h[i - 2] if i >= 2 else h[i - 1])
            if h[i] > s:
                d[i], sar[i], ep[i], afs[i] = 1.0, ep[i - 1], h[i], af
            else:
                d[i] = -1.0
                if l[i] < ep[i - 1]:
                    ep[i] = l[i]
                    afs[i] = min(afs[i - 1] + step, maxaf)
                else:
                    ep[i] = ep[i - 1]
                    afs[i] = afs[i - 1]
                sar[i] = s
    return pd.Series(d, index=df.index), pd.Series(sar, index=df.index)


def donchian_state(close, high, low, n):
    """Turtle-style: enter long when close > highest high of prior n bars;
    exit when close < lowest low of prior n bars."""
    hh = high.rolling(n).max().shift(1).to_numpy()
    ll = low.rolling(n).min().shift(1).to_numpy()
    c = close.to_numpy()
    st = np.full(len(c), np.nan)
    cur = 0.0
    for i in range(len(c)):
        if np.isnan(hh[i]):
            continue
        if cur == 0 and c[i] > hh[i]:
            cur = 1.0
        elif cur == 1 and c[i] < ll[i]:
            cur = 0.0
        st[i] = cur
    return pd.Series(st, index=close.index)


def ichimoku_above(close, high, low):
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2.0
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2.0
    span_a = ((tenkan + kijun) / 2.0).shift(26)
    span_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2.0).shift(26)
    top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    return close > top


def masked(cond, *refs):
    """Boolean -> float with NaN wherever any reference series is unwarmed."""
    m = None
    for r in refs:
        m = r.notna() if m is None else (m & r.notna())
    return cond.astype(float).where(m)


def edges(state):
    """Rising/falling edges of a 0/1 (float, NaN warmup) state series."""
    v = state.astype(float).to_numpy()
    idx = state.index
    ups, dns = [], []
    for i in range(1, len(v)):
        if v[i] == 1.0 and v[i - 1] == 0.0:
            ups.append(idx[i])
        elif v[i] == 0.0 and v[i - 1] == 1.0:
            dns.append(idx[i])
    return ups, dns


# ------------------------------------------------------------------- frames --
def load_daily():
    df = pd.read_csv(DATA, parse_dates=["ts"])
    df = df.dropna(subset=["close"]).sort_values("ts").set_index("ts")
    return df[["open", "high", "low", "close", "volume"]]


def to_weekly(df):
    w = df.resample("W-SUN").agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"})
    return w.dropna(subset=["close"])


# ------------------------------------------------------------------ variants --
def build_variants(d, w):
    """name -> (state series bull=1/bear=0/NaN warmup, frame)"""
    out = {}

    st = supertrend(d, 10, 3.0)
    out["ST(10,3) d"] = (masked(st["dir"] == 1, st["dir"]), d)
    st7 = supertrend(d, 7, 3.0)
    out["ST(7,3) d"] = (masked(st7["dir"] == 1, st7["dir"]), d)

    sma50 = d["close"].rolling(50).mean()
    sma200 = d["close"].rolling(200).mean()
    out["close>SMA50 d"] = (masked(d["close"] > sma50, sma50), d)
    out["close>SMA200 d"] = (masked(d["close"] > sma200, sma200), d)
    out["GC 50/200 d"] = (masked(sma50 > sma200, sma50, sma200), d)

    rd = rsi_wilder(d["close"])
    out["RSI14>50 d"] = (masked(rd > 50.0, rd), d)

    # MACD/PSAR are defined from bar 1 (standard conventions, no warmup mask)
    ema12 = d["close"].ewm(span=12, adjust=False).mean()
    ema26 = d["close"].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    out["MACD x d"] = ((macd > sig).astype(float), d)

    pdir, _ = psar_dir(d)
    out["PSAR flip d"] = ((pdir == 1).astype(float), d)

    out["Donch55 d"] = (donchian_state(d["close"], d["high"], d["low"], 55), d)

    stw = supertrend(w, 10, 3.0)
    out["ST(10,3) w"] = (masked(stw["dir"] == 1, stw["dir"]), w)

    w20 = w["close"].rolling(20).mean()
    out["close>20wMA w"] = (masked(w["close"] > w20, w20), w)

    wrsi = rsi_wilder(w["close"])
    out["RSI14>50 w"] = (masked(wrsi > 50.0, wrsi), w)
    out["RSI14>60 w"] = (masked(wrsi > 60.0, wrsi), w)

    wema12 = w["close"].ewm(span=12, adjust=False).mean()
    wema26 = w["close"].ewm(span=26, adjust=False).mean()
    wmacd = wema12 - wema26
    wsig = wmacd.ewm(span=9, adjust=False).mean()
    out["MACD x w"] = ((wmacd > wsig).astype(float), w)

    out["Donch20 w"] = (donchian_state(w["close"], w["high"], w["low"], 20), w)

    tenkan_w = (w["high"].rolling(9).max() + w["low"].rolling(9).min()) / 2.0
    kijun_w = (w["high"].rolling(26).max() + w["low"].rolling(26).min()) / 2.0
    span_a_w = ((tenkan_w + kijun_w) / 2.0).shift(26)
    span_b_w = ((w["high"].rolling(52).max() + w["low"].rolling(52).min()) / 2.0).shift(26)
    cloud_top = pd.concat([span_a_w, span_b_w], axis=1).max(axis=1)
    out["Ichimoku w"] = (masked(w["close"] > cloud_top, cloud_top), w)

    return out


# --------------------------------------------------------- bottom detection --
def detect_bottoms(d):
    low = d["low"]
    close = d["close"]
    prior_min = low.rolling(366, min_periods=60).min()
    post_min = low[::-1].rolling(366, min_periods=366).min()[::-1]
    cand = (low <= prior_min + 1e-12) & low.notna() & post_min.notna() & (low <= post_min + 1e-12)
    idx = d.index[cand.fillna(False)]
    clusters = []
    cur = []
    for day in idx:
        if cur and (day - cur[-1]).days > 45:
            clusters.append(cur)
            cur = []
        cur.append(day)
    if cur:
        clusters.append(cur)
    bottoms = []
    for cl in clusters:
        rep = min(cl, key=lambda t: d.loc[t, "low"])
        i = d.index.get_loc(rep)
        fwd = close.iloc[i + 1:i + 1 + 730]
        ratio = fwd.max() / close.iloc[i] if len(fwd) else np.nan
        if len(fwd) and ratio >= 2.0:
            bottoms.append({"date": rep, "low": d.loc[rep, "low"], "close": d.loc[rep, "close"],
                            "fwd_max_ratio": ratio, "suppl": False})
    return bottoms


# ------------------------------------------------------------------ measures --
def summarize(name, state, frame, flips, dns, bottoms, fwd_bars):
    """Per-variant table row + per-bottom first-flip cells."""
    close = frame["close"]
    cells = {}
    longs = {}
    for b in bottoms:
        bd = b["date"]
        last_obs = state.loc[:bd].dropna()
        if len(last_obs) and bool(last_obs.iloc[-1]):
            # already bull at the bottom (bear-rally flip or stale regime):
            # no post-bottom flip to time; record when it RE-ARMS (next 0->1)
            nxt = [f for f in flips if f >= bd and (f - bd).days <= MAX_DELAY]
            cells[bd] = None
            longs[bd] = {"rearm": (nxt[0] - bd).days if nxt else None}
            continue
        longs[bd] = False
        search = [f for f in flips if f >= bd and (f - bd).days <= MAX_DELAY]
        if not search:
            cells[bd] = None
        else:
            f = search[0]
            fclose = float(close.loc[f])
            cells[bd] = {"flip": f, "delay": (f - bd).days,
                         "pct_above": fclose / b["close"] - 1.0}
    warm = {}
    for b in bottoms:
        warm[b["date"]] = bool(state.loc[:b["date"]].notna().any())

    # whipsaws: bullish flip reversed within WHIP_WIN days
    n_whip = 0
    for f in flips:
        nxt = [x for x in dns if x > f]
        if nxt and (nxt[0] - f).days <= WHIP_WIN:
            n_whip += 1
    whip = n_whip / len(flips) if flips else np.nan

    # pre-bottom flips (crying wolf in the 365d before each bottom)
    pre = {}
    for b in bottoms:
        bd = b["date"]
        pre[bd] = sum(1 for f in flips if bd - pd.Timedelta(days=365) <= f < bd)

    # forward-return directional check on all flips vs baseline
    fwd_rets = []
    for f in flips:
        i = close.index.get_loc(f)
        if i + fwd_bars < len(close):
            fwd_rets.append(float(close.iloc[i + fwd_bars]) / float(close.iloc[i]) - 1.0)
    base = (close.shift(-fwd_bars) / close - 1.0).dropna()

    flips_12m = sum(1 for f in flips if f >= frame.index[-1] - pd.Timedelta(days=365))

    last = state.dropna()
    cur = bool(last.iloc[-1]) if len(last) else None
    since = None
    if len(last):
        s = last.astype(bool)
        opp = last.index[s == (not cur)]
        if len(opp):
            j = last.index.get_loc(opp[-1])
            since = last.index[j + 1] if j + 1 < len(last) else None
        else:
            since = last.index[0]

    return {
        "name": name, "first_valid": state.first_valid_index(), "cells": cells,
        "longs": longs, "warm": warm, "whip": whip, "flips": len(flips),
        "flips_12m": flips_12m,
        "pre": pre, "fwd_med": np.median(fwd_rets) if fwd_rets else np.nan,
        "base_med": float(base.median()), "cur": cur, "since": since,
    }


# ----------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    d = load_daily()
    w = to_weekly(d)
    print(f"DATA  daily {d.index[0].date()} .. {d.index[-1].date()} ({len(d)} bars) | "
          f"weekly {w.index[0].date()} .. {w.index[-1].date()} ({len(w)} bars)")

    bottoms = detect_bottoms(d)
    suppl_date = pd.Timestamp("2020-03-13")
    if all(b["date"] != suppl_date for b in bottoms):
        i = d.index.get_loc(suppl_date)
        fwd = d["close"].iloc[i + 1:i + 1 + 730]
        bottoms.append({"date": suppl_date, "low": float(d.loc[suppl_date, "low"]),
                        "close": float(d.loc[suppl_date, "close"]),
                        "fwd_max_ratio": float(fwd.max() / d.loc[suppl_date, "close"]),
                        "suppl": True})
    bottoms.sort(key=lambda b: b["date"])

    print("\n=== CYCLE BOTTOMS (mechanical: +/-365d low, >=2x within 730d; * = supplementary) ===")
    for b in bottoms:
        mark = " *" if b["suppl"] else "  "
        print(f" {mark} {b['date'].date()}  low {b['low']:>10,.2f}  close {b['close']:>10,.2f}  "
              f"fwd-max x{b['fwd_max_ratio']:.1f}")
    print("  * 2020-03-13 crash low fails the mechanical rule by $75 (2019-03-14 grind low 3,775")
    print("    undercuts 3,850) - added as a labelled V-recovery stress test, not a cycle trough.")

    variants = build_variants(d, w)
    flips_by = {}
    rows = {}
    for name, (state, frame) in variants.items():
        flips, dns = edges(state)
        flips_by[name] = (flips, dns, state, frame)
        fwd_bars = FWD_DAILY if name.endswith(" d") else FWD_WEEKLY
        rows[name] = summarize(name, state, frame, flips, dns, bottoms, fwd_bars)

    bdates = [b["date"] for b in bottoms]
    labels = [bd.strftime("%b%y") + ("*" if bd == suppl_date else "") for bd in bdates]

    print("\n=== FIRST BULLISH FLIP AFTER EACH BOTTOM (delay days / % above bottom close) ===")
    hdr = f"{'variant':<13}" + "".join(f" {lab:>14}" for lab in labels)
    print(hdr)
    print("-" * len(hdr))
    order = sorted(rows.values(),
                   key=lambda r: np.median([c["delay"] for c in r["cells"].values() if c]) if any(r["cells"].values()) else 9e9)
    for r in order:
        cells = []
        for bd in bdates:
            c = r["cells"][bd]
            if c is None:
                if r["longs"].get(bd):
                    nx = r["longs"][bd]["rearm"]
                    cells.append(f"long@b+{nx}d" if nx is not None else "long@b")
                else:
                    cells.append("    n/a" if r["warm"][bd] else " warmup")
            else:
                cells.append(f"+{c['delay']:>3}d/{c['pct_above']*100:>+5.0f}%")
        print(f"{r['name']:<13}" + "".join(f" {cell:>14}" for cell in cells))
    print("  warmup = variant not warmed by the bottom (n/a would overstate its speed);")
    print("  n/a = warmed, but no flip within 730 days.")
    print("  long@b = already bull at the bottom (bear-rally flip / stale regime) - no")
    print("           post-bottom flip to time; +Nd = re-arm delay (next observed flip).")

    print("\n=== QUALITY AXES (all history of each variant) ===")
    print(f"{'variant':<13} {'medDelay':>8} {'whip%':>6} {'flips':>5} {'flips12m':>8} "
          f"{'preBotF':>9} {'fwd1y m':>8} {'base1y':>8} {'cur':>4}  since")
    for r in order:
        dels = [c["delay"] for c in r["cells"].values() if c]
        medd = f"{np.median(dels):.0f}d(n={len(dels)})" if dels else "-"
        pres = "/".join(str(r["pre"][bd]) for bd in bdates)
        cur = "BULL" if r["cur"] else "bear"
        since = r["since"].date().isoformat() if r["since"] is not None else "-"
        fw = f"{r['fwd_med']*100:>+7.0f}%" if np.isfinite(r["fwd_med"]) else "     n/a"
        print(f"{r['name']:<13} {medd:>8} {r['whip']*100:>5.1f}% {r['flips']:>5} "
              f"{r['flips_12m']:>8} {pres:>9} {fw} {r['base_med']*100:>+7.0f}% {cur:>4}  {since}")
    print(f"  preBotF = bullish flips in the 365d before each bottom ({'/'.join(labels)}).")
    print(f"  whip% = flips reversed within {WHIP_WIN}d. fwd1y m vs base1y = median 1y forward return "
          "after flips vs the all-days baseline.")
    print("  CAVEAT: fwd1y is era-mixed (any random 2011-13 day had huge fwd returns) - read it as")
    print("  'do flips beat a random day', not as a strategy return.")

    print("\n=== FIRST FLIPPER AT EACH BOTTOM (fastest observed) ===")
    for bd in bdates:
        best = sorted(((r["cells"][bd]["delay"], r["name"]) for r in rows.values()
                       if r["cells"][bd]), key=lambda x: x[0])
        top = " | ".join(f"{nm} +{dd}d" for dd, nm in best[:4])
        print(f"  {bd.date()}: {top}")

    print("\n=== CURRENT STATE AS OF LAST CLOSE ===")
    for name, (flips, dns, state, frame) in flips_by.items():
        last = state.dropna()
        if not len(last):
            continue
        cur = "BULL" if last.iloc[-1] else "bear"
        r = rows[name]
        lvl = ""
        if name.startswith("ST"):
            stx = supertrend(frame, 10 if "(10," in name else 7, 3.0)
            stl = float(stx["st"].iloc[-1])
            lvl = f" | flip level {stl:,.0f}"
        print(f"  {name:<13} {cur} since {r['since'].date() if r['since'] is not None else '-'}{lvl}")

    if args.outdir:
        od = Path(args.outdir)
        od.mkdir(parents=True, exist_ok=True)
        recs = []
        for name, (flips, dns, state, frame) in flips_by.items():
            close = frame["close"]
            for f in flips:
                nxt = [x for x in dns if x > f]
                wh = bool(nxt and (nxt[0] - f).days <= WHIP_WIN)
                recs.append({"variant": name, "flip_date": f.date().isoformat(),
                             "price": float(close.loc[f]), "whipsaw": wh})
        pd.DataFrame(recs).to_csv(od / "flips.csv", index=False)
        agg = []
        for r in rows.values():
            dels = [c["delay"] for c in r["cells"].values() if c]
            agg.append({"variant": r["name"],
                        "med_delay": np.median(dels) if dels else None,
                        "whip": r["whip"], "flips": r["flips"], "flips_12m": r["flips_12m"],
                        **{f"delay_{bd.strftime('%Y')}": (r["cells"][bd]["delay"] if r["cells"][bd] else None) for bd in bdates},
                        **{f"pct_{bd.strftime('%Y')}": (r["cells"][bd]["pct_above"] if r["cells"][bd] else None) for bd in bdates},
                        **{f"long_{bd.strftime('%Y')}": bool(r["longs"].get(bd)) for bd in bdates},
                        **{f"rearm_{bd.strftime('%Y')}": (r["longs"].get(bd) or {}).get("rearm") for bd in bdates}})
        pd.DataFrame(agg).to_csv(od / "aggregates.csv", index=False)
        pd.DataFrame([{"date": b["date"].date().isoformat(), "low": b["low"], "close": b["close"],
                       "fwd_max_ratio": b["fwd_max_ratio"], "suppl": b["suppl"]} for b in bottoms]).to_csv(od / "bottoms.csv", index=False)
        print(f"\nwrote flips.csv / aggregates.csv / bottoms.csv to {od}")


if __name__ == "__main__":
    main()
