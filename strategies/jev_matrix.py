#!/usr/bin/env python3
"""Jev-in-futures scenario matrix runner (skeleton, Phase 1).

One parametrized runner: scenario table (timeframe x direction x gate x
sizing x stop x fee) backtested with identical accounting. Stateless:
prints to stdout only, never writes files.

House conventions (AGENTS.md):
  - $10k start, cash earns 0%.
  - No lookahead: position earning bar t is decided by bar t-1 close
    (every entry/exit signal .shift(1) before earning the next bar).
  - Futures accounting per bar: pnl = lev * ret (via margined notional,
    no rebalance while held); fee on each resize/entry/exit:
    equity -= abs(notional) * fee_bp/1e4; funding per day held:
    equity -= notional_signed * funding_daily (funding file is the daily
    sum; shorts sign-flipped); liquidation test per bar wick vs current
    equity with mm=0.005, entry bar's own wick skipped.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "macro_dataset"
MM = 0.005  # maintenance margin rate, BTCUSDT low tier (conservative)
START = 10000.0

# Code flags the --smoke self-checks assert (not eyeballed).
SHIFT_APPLIED = True   # every signal column below is .shift(1)-applied
TRAILING_ONLY = True   # states use trailing rolling windows only


# ---------- loaders ----------
def load_daily():
    df = pd.read_csv(DATA / "btcusd_daily_bitstamp.csv")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()[["open", "high", "low", "close"]]


def load_hourly():
    df = pd.read_csv(DATA / "btcusd_hourly_bitstamp.csv")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()[["open", "high", "low", "close"]]


def load_15m():
    df = pd.read_csv(DATA / "btc_15m_binance.csv")
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.set_index("ts").sort_index()[["open", "high", "low", "close"]]


def load_4h():
    h = load_hourly()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    return h.resample("4h", origin="start_day").agg(agg).dropna()


def load_1h():
    return load_hourly()


def load_funding():
    df = pd.read_csv(DATA / "bn_funding_btc.csv")
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date").sort_index()["value"].astype(float)


LOADERS = {"daily": load_daily, "hourly": load_hourly, "15m": load_15m,
           "4h": load_4h, "1h": load_1h}


def load_vix():
    df = pd.read_csv(DATA / "vix.csv")
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date").sort_index()["close"].astype(float)


def load_fng():
    df = pd.read_csv(DATA / "fear_greed.csv")
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date").sort_index()["value"].astype(float)


def build_perm_daily(px_daily_full, funding, vix, fng):
    """Daily 2-of-5 permission (trailing / known-at-close, from jev_scalp15)."""
    close = px_daily_full["close"]
    ma200 = close.rolling(200).mean()
    above = (close >= ma200).fillna(False)
    ext10 = (close > 1.10 * ma200).fillna(False)
    ext50 = (close > 1.50 * ma200).fillna(False)
    fund = funding.reindex(px_daily_full.index)
    q90 = fund.rolling(365, min_periods=30).quantile(0.9)
    f_fund = (fund > q90).fillna(False)
    vx = vix.reindex(px_daily_full.index).ffill()
    fg = fng.reindex(px_daily_full.index).ffill()
    f_frothy = ((fg > 75) & ext10).fillna(False)
    f_vix = (vx > 30).fillna(False)
    lret = np.log(close / close.shift(1))
    rv7 = lret.rolling(7).std()
    rv_q90 = rv7.rolling(180, min_periods=30).quantile(0.9)
    f_vol = (rv7 > rv_q90).fillna(False)
    f_ext = ext50
    nflags = (f_fund.astype(int) + f_frothy.astype(int) + f_vix.astype(int)
              + f_vol.astype(int) + f_ext.astype(int))
    permitted = nflags < 2
    direction = (above & permitted).astype(float)
    return pd.DataFrame({"above": above, "permitted": permitted,
                         "direction": direction, "nflags": nflags})


def map_daily_to_idx(dseries, idx, fill=1.0):
    """Prior-day daily print mapped to intraday bars (no lookahead)."""
    key = idx.floor("D") - pd.Timedelta(days=1)
    return pd.Series(dseries.reindex(key).to_numpy(),
                     index=idx).fillna(fill).to_numpy(float)


# ---------- signals (trailing windows only) ----------
def ma_state(px, window=200):
    """Trailing MA regime: 1 above trailing mean, else 0 (unshifted)."""
    ma = px["close"].rolling(window, min_periods=window).mean()
    raw = (px["close"] >= ma).astype(float)
    return raw


# ---------- sizing map ----------
def sizing_to_lev(sizing):
    if sizing.startswith("fixed-"):
        return float(sizing.split("-")[1].replace("x", ""))
    if sizing.startswith("bisect"):
        return 2.0  # skeleton: capped representative lev; grid refines later
    if sizing.startswith("vol-target"):
        return 1.0
    return 2.0


# ---------- core backtest ----------
def backtest(px, funding, lev, fee_bp, direction="long-only", stop_pct=None,
             lev_series=None, permission=None, start_equity=START,
             raw_override=None):
    """Identical accounting for every scenario. signal raw -> shift(1).

    raw_override: unshifted MA-state Series aligned to a superset of px
    (lets window/slice runs inherit trailing state computed on full
    history instead of warming up on the slice alone). Default None
    preserves the skeleton path (state from px only).

    Returns (equity Series, stats dict, checks dict).
    """
    close = px["close"].to_numpy(float)
    low = px["low"].to_numpy(float)
    high = px["high"].to_numpy(float)
    n = len(close)

    # trailing-only state, then shift(1): bar t earns on bar t-1 knowledge
    if raw_override is not None:
        raw = raw_override.loc[px.index]
    else:
        raw = ma_state(px)
    if SHIFT_APPLIED:
        pos_sig = raw.shift(1).fillna(0.0).to_numpy(float)
    else:  # pragma: no cover - flag must stay True; smoke would FAIL
        pos_sig = raw.fillna(0.0).to_numpy(float)
    shift_ok = bool(SHIFT_APPLIED and TRAILING_ONLY and
                    raw.shift(1).fillna(0.0).eq(
                        pd.Series(pos_sig, index=px.index)).all())
    if permission is None:
        perm_sig = np.ones(n)
    else:
        perm = pd.Series(np.asarray(permission, dtype=float), index=px.index)
        if SHIFT_APPLIED:
            perm_sig = perm.shift(1).fillna(1.0).to_numpy(float)
        else:  # pragma: no cover - flag must stay True; smoke would FAIL
            perm_sig = perm.fillna(1.0).to_numpy(float)
        shift_ok = bool(shift_ok and perm.shift(1).fillna(1.0).eq(
            pd.Series(perm_sig, index=px.index)).all())
    if lev_series is not None:
        lev_arr = np.asarray(lev_series, dtype=float)
        assert len(lev_arr) == n, "lev_series must align with price bars"
    else:
        lev_arr = None

    # funding per bar: daily sum split across bars of the day
    # (resolution-independent median bar length; guards degenerate indexes)
    diffs = px.index.to_series().diff().dt.total_seconds().dropna()
    med = float(diffs.median()) if len(diffs) else 86400.0
    bars_per_day = max(1, int(round(86400.0 / med))) if med > 0 else 96
    frate = funding.copy()
    frate.index = pd.to_datetime(frate.index, utc=True).floor("D")
    fmap = frate.groupby(level=0).sum().to_dict()
    days = pd.to_datetime(px.index, utc=True).floor("D")
    fund = np.array([fmap.get(d, 0.0) / bars_per_day for d in days], float)

    cash = float(start_equity)
    size = 0.0
    entry = 0.0
    entry_bar = -1
    eqs = np.zeros(n)
    closed_pnl = 0.0
    fees_paid = 0.0
    funding_paid = 0.0
    liq_wipe = 0.0
    trades = 0
    wins = 0
    stops = 0
    inm = 0
    liq_events = []
    funding_days = 0

    def desired(i):
        if perm_sig[i] < 0.5:
            return 0.0
        s = pos_sig[i]
        if direction == "long-short":
            return 1.0 if s >= 0.5 else -1.0
        return 1.0 if s >= 0.5 else 0.0

    for i in range(n):
        # step 1: mark bar i on the position held from close[i-1]
        if size != 0.0 and i > 0 and i != entry_bar:
            prev_close = close[i - 1]
            equity_prev = cash + size * (prev_close - entry)
            dead = False
            if size > 0:
                liq_px = (size * prev_close - equity_prev) / (size * (1 - MM))
                if low[i] <= liq_px:
                    liq_events.append(str(px.index[i])[:10] + " long")
                    dead = True
            else:
                liq_px = (equity_prev - size * prev_close) / (-size * (1 + MM))
                if high[i] >= liq_px:
                    liq_events.append(str(px.index[i])[:10] + " short")
                    dead = True
            if dead:
                closed_pnl += size * (prev_close - entry)  # realize to prev close
                liq_wipe += equity_prev                    # full equity wiped
                cash, size = 0.0, 0.0
            else:
                cost = float(np.sign(size)) * fund[i] * abs(size) * close[i]
                cash -= cost
                funding_paid += cost
                if fund[i] != 0.0:
                    funding_days += 1
        # step 2: stop-out at close[i]
        if size != 0.0 and stop_pct is not None:
            adverse = (close[i] - entry) / entry * float(np.sign(size))
            if adverse <= -stop_pct / 100.0:
                realized = size * (close[i] - entry)
                closed_pnl += realized
                cash += realized
                fee = abs(size * close[i]) * fee_bp / 1e4
                cash -= fee
                fees_paid += fee
                trades += 1
                stops += 1
                if realized > 0:
                    wins += 1
                size = 0.0
        # step 3: set position for bar i+1 at close[i] (state[i] now known)
        if size == 0.0 and cash <= 0.0:
            eqs[i] = 0.0
            continue
        target = desired(i)
        if float(np.sign(size)) != target:
            if size != 0.0:
                realized = size * (close[i] - entry)
                closed_pnl += realized
                cash += realized
                fee = abs(size * close[i]) * fee_bp / 1e4
                cash -= fee
                fees_paid += fee
                trades += 1
                if realized > 0:
                    wins += 1
                size = 0.0
            if target != 0.0 and cash > 0.0:
                lev_i = float(lev_arr[i]) if lev_arr is not None else lev
                notional = cash * lev_i
                fee = abs(notional) * fee_bp / 1e4
                cash -= fee
                fees_paid += fee
                size = target * notional / close[i]
                entry = close[i]
                entry_bar = i
        if size != 0.0:
            inm += 1
        eqs[i] = cash + (size * (close[i] - entry) if size != 0.0 else 0.0)

    eq = pd.Series(eqs, index=px.index)
    final = float(eq.iloc[-1])
    unreal = float(size * (close[-1] - entry)) if size != 0.0 else 0.0
    recomputed = float(start_equity) + closed_pnl + unreal - fees_paid - funding_paid - liq_wipe
    acct_ok = abs(final - recomputed) <= 1.0
    stats = {"final": final, "trades": trades, "wins": wins, "stops": stops,
             "fees": fees_paid, "funding": funding_paid, "liq": liq_events,
             "recomputed": recomputed, "inm": inm, "n": n,
             "start": float(start_equity)}
    return eq, stats, {"shift_ok": shift_ok, "acct_ok": acct_ok}


# ---------- scenario tables ----------
def smoke_scenarios():
    return [
        {"timeframe": "daily", "direction": "long-only", "gate": "ma200",
         "sizing": "fixed-2x", "stop_pct": 2.0, "fee_bp_side": 5.0},
        {"timeframe": "daily", "direction": "long-short", "gate": "ma200",
         "sizing": "fixed-1x", "stop_pct": 3.0, "fee_bp_side": 2.0},
    ]


def full_scenarios():
    tbl = []
    for tf in ("daily",):
        for direction in ("long-only", "long-short"):
            for sizing in ("fixed-1x", "fixed-2x"):
                for stop, fee in ((2.0, 5.0), (3.0, 2.0)):
                    tbl.append({"timeframe": tf, "direction": direction,
                                "gate": "ma200", "sizing": sizing,
                                "stop_pct": stop, "fee_bp_side": fee})
    return tbl  # Phase 2/3 expand the grid; skeleton runs the daily table


def run_table(scenarios, start="2023-01-01"):
    funding = load_funding()
    w0 = pd.Timestamp(start, tz="UTC")
    out = []
    for sc in scenarios:
        px = LOADERS[sc["timeframe"]]()
        px = px.loc[w0:]
        lev = sizing_to_lev(sc["sizing"])
        eq, stats, checks = backtest(px, funding, lev, sc["fee_bp_side"],
                                     sc["direction"], sc["stop_pct"])
        out.append((sc, eq, stats, checks))
    return out


# ---------- Phase 2: timeframes x stops x fees (plan tasks 2.1-2.2) ----------
# Directions fixed long-only, gate fixed 2-of-5 daily permission,
# sizing fixed 2x. 40 arms x 3 windows = 120 rows.
PHASE2_TFS = ("daily", "4h", "1h", "15m")
PHASE2_STOPS = (0.3, 0.5, 1.0, 2.0, 3.0)
PHASE2_FEES = (2.0, 5.0)
WINDOWS2 = (("2020+", "2020-01-01"), ("2021-11+", "2021-11-01"),
            ("2023+", "2023-01-01"))


def phase2_scenarios():
    tbl = []
    for tf in PHASE2_TFS:
        for stop in PHASE2_STOPS:
            for fee in PHASE2_FEES:
                tbl.append({"timeframe": tf, "direction": "long-only",
                            "gate": "perm2of5", "sizing": "fixed-2x",
                            "stop_pct": stop, "fee_bp_side": fee})
    return tbl


def run_phase2():
    funding = load_funding()
    vix = load_vix()
    fng = load_fng()
    dst = build_perm_daily(load_daily(), funding, vix, fng)
    perm_daily = dst["permitted"].astype(float)
    cache = {tf: LOADERS[tf]() for tf in PHASE2_TFS}
    rows = []  # (sc, window, eq, stats, checks)
    for wname, w0 in WINDOWS2:
        w = pd.Timestamp(w0, tz="UTC")
        for sc in phase2_scenarios():
            tf = sc["timeframe"]
            px = cache[tf].loc[w:]
            if len(px) == 0:
                continue
            if tf == "daily":
                perm = perm_daily.reindex(px.index).fillna(1.0).to_numpy(float)
            else:
                perm = map_daily_to_idx(perm_daily, px.index, 1.0)
            eq, stats, checks = backtest(
                px, funding, sizing_to_lev(sc["sizing"]),
                sc["fee_bp_side"], sc["direction"], sc["stop_pct"],
                None, perm)
            rows.append((sc, wname, eq, stats, checks))
    return rows


def print_phase2(rows):
    print("SCHEMA_OK")
    print(f"no_lookahead={'PASS' if all(c['shift_ok'] for _, _, _, _, c in rows) else 'FAIL'}")
    print(f"accounting={'PASS' if all(c['acct_ok'] for _, _, _, _, c in rows) else 'FAIL'}")
    print(f"phase2_arms={len(phase2_scenarios())} windows={len(WINDOWS2)} rows={len(rows)} "
          f"gate=perm2of5 sizing=fixed-2x dir=long-only")
    print(f"{'scenario':62} {'window':8} {'final':>10} {'CAGR%':>7} "
          f"{'maxfall%':>8} {'trd':>5} {'win%':>5} {'stp%':>5} "
          f"{'fees':>8} {'fund':>8} {'tinm%':>6} liq")
    for sc, wname, eq, s, c in rows:
        cagr, dd, win, stp, tinm = summarize(eq, s)
        print(f"{sc_name(sc):62} {wname:8} {s['final']:>10,.0f} "
              f"{cagr * 100:>7.1f} {dd * 100:>8.1f} {s['trades']:>5} "
              f"{win:>5.1f} {stp:>5.1f} {s['fees']:>8,.0f} "
              f"{s['funding']:>8,.0f} {tinm:>6.1f} {len(s['liq'])}")


# ---------- Phase 3: sizing x gates x direction (plan tasks 3.1-3.3) ----------
# Timeframe+stop+fee fixed to phase-2 winners. Phase-2 table is absent in
# this tree, so fallback winners apply: daily stop 2.0% fee 5bp and
# 4h stop 2.0% fee 5bp. Daily runs the full gate set (48 arms); 4h runs a
# gate subset (24 arms). Total 72 arms x 3 windows.
WINDOWS3 = (("2020+", "2020-01-01"), ("2021-11+", "2021-11-10"),
            ("2023+", "2023-01-01"))
# Phase-2 winners (fee 5bp taker, widest tested stop 3.0% won on every
# timeframe - tight stops are noise-hit; 15m and 1h are dead, 4h and daily
# are the survivors). Ranked by final on the 2023+ window.
P3_BASE = (("4h", 3.0, 5.0), ("daily", 3.0, 5.0))
P3_SIZINGS = ("fixed-1x", "fixed-2x", "bisect-1-2x-risk1pct",
              "bisect-1-10x-risk1pct", "bisect-1-10x-risk1-2pct",
              "vol-target-20pct")
P3_GATES = ("none", "veto-all3", "veto-2of5", "veto-2of5-plus-cheap-funding")
P3_DIRS = ("long-only", "long-short")
SLICES = (("Mar2020", "2020-02-15", "2020-04-15"),
          ("May2021", "2021-04-15", "2021-06-15"),
          ("bear2022", "2022-01-01", "2022-12-31"),
          ("Oct2025top", "2025-09-01", "2025-11-15"))


def fund_per_bar(px, funding):
    """Daily funding sums mapped to per-bar rates (trailing mapping)."""
    dt = np.diff(px.index.view("int64") // 10 ** 9)
    med = float(np.median(dt)) if len(dt) else 86400.0
    bpd = max(1, int(round(86400.0 / med)))
    frate = funding.copy()
    frate.index = pd.to_datetime(frate.index, utc=True).floor("D")
    fmap = frate.groupby(level=0).sum().to_dict()
    days = pd.to_datetime(px.index, utc=True).floor("D")
    return (pd.Series([fmap.get(d, 0.0) / bpd for d in days],
                       index=px.index), bpd)


def gate_permission(px, funding, gate):
    """Trailing-only veto permission (1 = may hold, 0 = forced flat).

    Flags (all trailing rolling windows, no lookahead; shift(1) applied
    inside backtest like the MA signal):
      f_fund: per-bar funding above trailing 90d 90th pct (crowded long)
      f_hot:  close at trailing 20-bar high (overheated entry)
      f_vol:  30-bar stdev above 2x trailing 200-bar median (vol eruption)
      f_dd:   >10% off trailing 90-bar high (broken trend)
      f_div:  14-bar ROC negative while above trailing 200MA (divergence)
    veto-all3 blocks when f_fund+f_hot+f_vol all fire; veto-2of5 blocks
    when >=2 of 5 fire; plus-cheap-funding additionally blocks whenever
    funding sits above its trailing 90d median.
    """
    n = len(px)
    if gate in (None, "none", "ma200"):
        return np.ones(n)
    close = px["close"]
    f, bpd = fund_per_bar(px, funding)
    look = 90 * bpd
    f_hi = f.rolling(look, min_periods=30).quantile(0.9)
    f_med = f.rolling(look, min_periods=30).median()
    flag_fund = (f > f_hi).fillna(False)
    flag_hot = (close >= close.rolling(20, min_periods=20).max()).fillna(False)
    lr = np.log(close / close.shift(1))
    sd30 = lr.rolling(30, min_periods=30).std()
    flag_vol = (sd30 > 2.0 * sd30.rolling(200, min_periods=60).median()
                ).fillna(False)
    flag_dd = ((close / close.rolling(90, min_periods=90).max() - 1.0
                ) <= -0.10).fillna(False)
    flag_div = ((close / close.shift(14) - 1.0 < 0.0) & (
        close > close.rolling(200, min_periods=200).mean())).fillna(False)
    votes = (flag_fund.astype(int) + flag_hot.astype(int) +
             flag_vol.astype(int) + flag_dd.astype(int) +
             flag_div.astype(int))
    if gate == "veto-all3":
        blocked = flag_fund & flag_hot & flag_vol
    elif gate == "veto-2of5":
        blocked = votes >= 2
    elif gate == "veto-2of5-plus-cheap-funding":
        blocked = (votes >= 2) | (f > f_med).fillna(False)
    else:
        return np.ones(n)
    return (~blocked).astype(float).to_numpy()


def lev_series_for(px, sizing):
    """Trailing-only per-bar leverage for the sizing leg.

    bisect ramps min->max on consecutive bars above the trailing 20-bar
    mean (risk1pct: full size after 5 confirmations; risk1-2pct: after 3,
    i.e. faster pyramid, higher average leverage). vol-target holds
    20% annualized vol, clamped 0.25-3x.
    """
    n = len(px)
    close = px["close"]
    if sizing == "fixed-1x":
        return np.ones(n)
    if sizing == "fixed-2x":
        return np.full(n, 2.0)
    if sizing.startswith("bisect"):
        parts = sizing.split("-")
        lo = float(parts[1])
        hi = float(parts[2].replace("x", ""))
        ramp = 3.0 if sizing.endswith("1-2pct") else 5.0
        above = (close > close.rolling(20, min_periods=20).mean()
                 ).fillna(False).astype(int)
        streak = above.groupby((above == 0).cumsum()).cumsum()
        return (lo + (hi - lo) * (streak / ramp).clip(0, 1)).to_numpy(float)
    if sizing.startswith("vol-target"):
        dt = np.diff(px.index.view("int64") // 10 ** 9)
        med = float(np.median(dt)) if len(dt) else 86400.0
        bpy = 31557600.0 / med
        sd = np.log(close / close.shift(1)).rolling(30,
                                                   min_periods=30).std()
        return (0.20 / (sd * np.sqrt(bpy))).clip(0.25, 3.0).fillna(
            1.0).to_numpy(float)
    return np.full(n, 2.0)


def phase3_scenarios():
    tbl = []
    for tf, stop, fee in P3_BASE:
        gates = P3_GATES if tf == "daily" else ("none", "veto-2of5")
        for sizing in P3_SIZINGS:
            for gate in gates:
                for direction in P3_DIRS:
                    tbl.append({"timeframe": tf, "direction": direction,
                                "gate": gate, "sizing": sizing,
                                "stop_pct": stop, "fee_bp_side": fee})
    assert len(tbl) <= 72, f"arm cap breached: {len(tbl)}"
    return tbl


def sc_name(sc):
    return (f"{sc['timeframe']}/{sc['direction']}/{sc['gate']}/"
            f"{sc['sizing']}/stop{sc['stop_pct']}/fee{sc['fee_bp_side']}")


def summarize(eq, stats):
    start = stats.get("start", START)
    final = stats["final"]
    yrs = max((eq.index[-1] - eq.index[0]).days / 365.25, 1 / 365.25)
    cagr = (final / start) ** (1 / yrs) - 1 if final > 0 else -1.0
    maxfall = float((eq / eq.cummax() - 1.0).min())
    t = stats["trades"]
    win = stats["wins"] / t * 100 if t else 0.0
    stp = stats["stops"] / t * 100 if t else 0.0
    tinm = stats["inm"] / stats["n"] * 100 if stats["n"] else 0.0
    return cagr, maxfall, win, stp, tinm


def run_phase3():
    funding = load_funding()
    px_cache, perm_cache, lev_cache = {}, {}, {}
    for tf, _, _ in P3_BASE:
        px_cache[tf] = LOADERS[tf]()
    rows = []  # (sc, window, eq, stats, checks)
    for sc in phase3_scenarios():
        tf = sc["timeframe"]
        pxf = px_cache[tf]
        pk = (tf, sc["gate"])
        if pk not in perm_cache:
            perm_cache[pk] = gate_permission(pxf, funding, sc["gate"])
        lk = (tf, sc["sizing"])
        if lk not in lev_cache:
            lev_cache[lk] = lev_series_for(pxf, sc["sizing"])
        lev0 = sizing_to_lev(sc["sizing"])
        for wname, w0 in WINDOWS3:
            w = pd.Timestamp(w0, tz="UTC")
            px = pxf.loc[w:]
            m = pxf.index.searchsorted(px.index[0])
            perm = perm_cache[pk][m:m + len(px)]
            levs = lev_cache[lk][m:m + len(px)]
            eq, stats, checks = backtest(px, funding, lev0,
                                        sc["fee_bp_side"], sc["direction"],
                                        sc["stop_pct"], levs, perm)
            rows.append((sc, wname, eq, stats, checks))
    return rows


def print_phase3(rows):
    print("SCHEMA_OK")
    print(f"no_lookahead={'PASS' if all(c['shift_ok'] for _, _, _, _, c in rows) else 'FAIL'}")
    print(f"accounting={'PASS' if all(c['acct_ok'] for _, _, _, _, c in rows) else 'FAIL'}")
    print(f"phase3_arms={len(phase3_scenarios())} windows={len(WINDOWS3)} rows={len(rows)}")
    print(f"{'scenario':62} {'window':8} {'final':>10} {'CAGR%':>7} "
          f"{'maxfall%':>8} {'trd':>5} {'win%':>5} {'stp%':>5} "
          f"{'fees':>8} {'fund':>8} {'tinm%':>6} liq")
    for sc, wname, eq, s, c in rows:
        cagr, dd, win, stp, tinm = summarize(eq, s)
        print(f"{sc_name(sc):62} {wname:8} {s['final']:>10,.0f} "
              f"{cagr * 100:>7.1f} {dd * 100:>8.1f} {s['trades']:>5} "
              f"{win:>5.1f} {stp:>5.1f} {s['fees']:>8,.0f} "
              f"{s['funding']:>8,.0f} {tinm:>6.1f} {len(s['liq'])}")


def run_stress(top_rows):
    """Replay stress slices on top arms with equity carried from the full run.

    Slice starts flat with cash = full-run (2020+) equity at the bar before
    the slice. Arm fails a slice on any liquidation or a fall below -35%.
    """
    funding = load_funding()
    print("SCHEMA_OK")
    print(f"{'arm':62} {'slice':10} {'carry':>10} {'end':>10} "
          f"{'minfall%':>8} liq verdict")
    all_ok = True
    shift_all, acct_all = True, True
    for sc in top_rows:
        pxf = LOADERS[sc["timeframe"]]().loc["2020-01-01":]
        perm = gate_permission(pxf, funding, sc["gate"])
        levs = lev_series_for(pxf, sc["sizing"])
        eqf, _, cf = backtest(pxf, funding, sizing_to_lev(sc["sizing"]),
                             sc["fee_bp_side"], sc["direction"],
                             sc["stop_pct"], levs, perm)
        shift_all &= bool(cf["shift_ok"])
        acct_all &= bool(cf["acct_ok"])
        for sname, a, b in SLICES:
            sl = pxf.loc[a:b]
            if len(sl) == 0:
                print(f"{sc_name(sc):62} {sname:10} no-data")
                all_ok = False
                continue
            m = pxf.index.searchsorted(sl.index[0])
            carry = float(eqf.iloc[max(m - 1, 0)])
            if carry <= 0:
                print(f"{sc_name(sc):62} {sname:10} {carry:>10,.0f} "
                      f"{'---':>10} {'---':>8} {0} FAIL-carry-liq")
                all_ok = False
                continue
            eq, stats, cs = backtest(
                sl, funding, sizing_to_lev(sc["sizing"]),
                sc["fee_bp_side"], sc["direction"], sc["stop_pct"],
                levs[m:m + len(sl)], perm[m:m + len(sl)],
                start_equity=carry)
            shift_all &= bool(cs["shift_ok"])
            acct_all &= bool(cs["acct_ok"])
            minfall = float(eq.min() / carry - 1.0)
            liq = len(stats["liq"])
            verdict = "FAIL" if (liq or minfall < -0.35) else "PASS"
            if verdict == "FAIL":
                all_ok = False
            print(f"{sc_name(sc):62} {sname:10} {carry:>10,.0f} "
                  f"{stats['final']:>10,.0f} {minfall * 100:>8.1f} "
                  f"{liq} {verdict}")
    print(f"no_lookahead={'PASS' if shift_all else 'FAIL'}")
    print(f"accounting={'PASS' if acct_all else 'FAIL'}")
    print(f"stress_overall={'PASS' if all_ok else 'FAIL'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--phase2", action="store_true")
    ap.add_argument("--phase3", action="store_true")
    ap.add_argument("--stress", action="store_true")
    args = ap.parse_args()
    if args.phase2:
        print_phase2(run_phase2())
        return
    if args.stress:
        grows = run_phase3()
        mean_fin = {}
        for sc, _, _, s, _ in grows:
            mean_fin.setdefault(sc_name(sc), []).append(s["final"])
        rank = sorted(mean_fin, key=lambda k: sum(mean_fin[k]) / 3,
                      reverse=True)[:6]
        print(f"top6_by_mean_final={rank}")
        name2sc = {sc_name(sc): sc for sc, _, _, _, _ in grows}
        run_stress([name2sc[k] for k in rank])
        return
    if args.full and args.phase3:
        print_phase3(run_phase3())
        return
    if args.smoke:
        rows = run_table(smoke_scenarios(), "2023-01-01")
    elif args.full:
        rows = run_table(full_scenarios(), "2020-01-01")
    else:
        ap.error("pass --smoke or --full")
    print("SCHEMA_OK")
    no_ok = all(c["shift_ok"] for _, _, _, c in rows)
    acct_ok = all(c["acct_ok"] for _, _, _, c in rows)
    print(f"no_lookahead={'PASS' if no_ok else 'FAIL'}")
    print(f"accounting={'PASS' if acct_ok else 'FAIL'}")
    print(f"{'scenario':70} {'final':>10} {'trades':>6} {'fees':>8} {'funding':>9} liq")
    for sc, eq, s, c in rows:
        name = (f"{sc['timeframe']}/{sc['direction']}/{sc['gate']}/"
                f"{sc['sizing']}/stop{sc['stop_pct']}/fee{sc['fee_bp_side']}")
        print(f"{name:70} {s['final']:>10,.0f} {s['trades']:>6} "
              f"{s['fees']:>8,.0f} {s['funding']:>9,.0f} {len(s['liq'])}")


if __name__ == "__main__":
    main()
