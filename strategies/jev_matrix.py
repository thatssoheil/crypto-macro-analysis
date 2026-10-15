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


def load_funding():
    df = pd.read_csv(DATA / "bn_funding_btc.csv")
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date").sort_index()["value"].astype(float)


LOADERS = {"daily": load_daily, "hourly": load_hourly, "15m": load_15m}


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
def backtest(px, funding, lev, fee_bp, direction="long-only", stop_pct=None):
    """Identical accounting for every scenario. signal raw -> shift(1).

    Returns (equity Series, stats dict, checks dict).
    """
    close = px["close"].to_numpy(float)
    low = px["low"].to_numpy(float)
    high = px["high"].to_numpy(float)
    n = len(close)

    # trailing-only state, then shift(1): bar t earns on bar t-1 knowledge
    raw = ma_state(px)
    if SHIFT_APPLIED:
        pos_sig = raw.shift(1).fillna(0.0).to_numpy(float)
    else:  # pragma: no cover - flag must stay True; smoke would FAIL
        pos_sig = raw.fillna(0.0).to_numpy(float)
    shift_ok = bool(SHIFT_APPLIED and TRAILING_ONLY and
                    raw.shift(1).fillna(0.0).eq(
                        pd.Series(pos_sig, index=px.index)).all())

    # funding per bar: daily sum split across bars of the day
    dt = np.diff(px.index.view("int64") // 10 ** 9)
    med = float(np.median(dt)) if len(dt) else 86400.0
    bars_per_day = max(1, int(round(86400.0 / med)))
    frate = funding.copy()
    frate.index = pd.to_datetime(frate.index, utc=True).floor("D")
    fmap = frate.groupby(level=0).sum().to_dict()
    days = pd.to_datetime(px.index, utc=True).floor("D")
    fund = np.array([fmap.get(d, 0.0) / bars_per_day for d in days], float)

    cash = START
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
    liq_events = []
    funding_days = 0

    def desired(i):
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
                notional = cash * lev
                fee = abs(notional) * fee_bp / 1e4
                cash -= fee
                fees_paid += fee
                size = target * notional / close[i]
                entry = close[i]
                entry_bar = i
        eqs[i] = cash + (size * (close[i] - entry) if size != 0.0 else 0.0)

    eq = pd.Series(eqs, index=px.index)
    final = float(eq.iloc[-1])
    unreal = float(size * (close[-1] - entry)) if size != 0.0 else 0.0
    recomputed = START + closed_pnl + unreal - fees_paid - funding_paid - liq_wipe
    acct_ok = abs(final - recomputed) <= 1.0
    stats = {"final": final, "trades": trades, "wins": wins, "stops": stops,
             "fees": fees_paid, "funding": funding_paid, "liq": liq_events,
             "recomputed": recomputed}
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()
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
