#!/usr/bin/env python3
"""
MA-LENGTH HOLDOUT TEST - pre-declared 2026-11-04

WHY THIS EXISTS
The six-length drawdown sweep (strategies/dd_protection_sweep.py) picked the 100-day
average as the best of six on 2017-2026. Picking the best of six on one window is
parameter selection, not evidence. This script tests that choice on a window it was
NOT selected on.

FROZEN DESIGN (written before the run, not edited after)
  Selection sample : 2017-01-01 .. 2026-11-01   (where 100 was chosen)
  Holdout sample   : 2011-08-18 .. 2016-12-31   (Bitstamp history, disjoint)

  Rule under test  : long when the PRIOR close > N-day average of close, else cash.
                     Daily closes, no lookahead, cash earns 0%, no costs in the base case.

  PASS CRITERIA - all four must hold on the holdout, or the 100-day switch stays a
  hypothesis and does not become the execution rule:
    1. MA100 terminal wealth > buy-and-hold.
    2. MA100 max drawdown better (smaller) than buy-and-hold.
    3. MA100 beats MA200 on BOTH metrics.
    4. Robustness inside the holdout: survives 0.2% cost per switch AND a 3-day
       execution delay, and beats buy-and-hold in at least 2 of the 3 sub-blocks
       (2011-2012, 2013-2015, 2016).

  Nothing below selects a new parameter. The lengths are fixed at 50/100/200 and the
  costs and delays are fixed in the criteria above.

Caveats stated up front: the holdout is 5.4 years and contains roughly two cycles, so a
pass is weak evidence and a fail is strong evidence. Daily closes only. No slippage beyond
the stated cost. Nothing here says anything about 2027.
"""
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"
HOLDOUT = ("2011-08-18", "2016-12-31")
SELECTION = ("2017-01-01", "2026-11-01")
SUBBLOCKS = [("2011-08-18", "2012-12-31"), ("2013-01-01", "2015-12-31"),
             ("2016-01-01", "2016-12-31")]


def btc():
    df = pd.read_csv(DATA / "btcusd_daily_bitstamp.csv")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()["close"]


def run(px, n, cost_per_flip=0.0, delay=0):
    """MA switch. cost_per_flip in decimal (0.002 = 0.2%). delay in days of extra lag."""
    ma = px.rolling(n).mean()
    sig = (px >= ma).astype(float)
    sig[ma.isna()] = 1.0
    pos = sig.shift(1 + delay).fillna(1.0)
    rets = px.pct_change().fillna(0)
    flips = pos.diff().abs().fillna(0)
    net = rets * pos - flips * cost_per_flip
    eq = (1 + net).cumprod() * 10000
    dd = (eq / eq.cummax() - 1).min() * 100
    return {"final": float(eq.iloc[-1]), "max_dd": float(dd),
            "flips": int((flips > 0).sum()), "years": len(px) / 365.25}


def bh(px, start_cash=10000):
    eq = (1 + px.pct_change().fillna(0)).cumprod() * start_cash
    return {"final": float(eq.iloc[-1]), "max_dd": float((eq / eq.cummax() - 1).min() * 100),
            "flips": 0, "years": len(px) / 365.25}


def table(label, px, cost=0.0, delay=0):
    print(f"\n  {label}")
    print(f"    {'strategy':22s} {'final':>14s} {'maxDD':>9s} {'flips':>6s}")
    b = bh(px)
    print(f"    {'buy & hold':22s} ${b['final']:>13,.0f} {b['max_dd']:>8.1f}% {b['flips']:>6d}")
    out = {}
    for n in (50, 100, 200):
        r = run(px, n, cost, delay)
        out[n] = r
        print(f"    {f'MA{n} switch':22s} ${r['final']:>13,.0f} {r['max_dd']:>8.1f}% {r['flips']:>6d}")
    return b, out


print("=" * 74)
print("MA-LENGTH HOLDOUT - pre-declared 2026-11-04")
print("=" * 74)
full = btc()

print("\n[1] SELECTION SAMPLE (where 100 was chosen) - context only, not evidence")
sel = full.loc[SELECTION[0]:SELECTION[1]]
table(f"2017-01-01 -> 2026-11-01", sel)

print("\n[2] HOLDOUT SAMPLE (100 was NOT selected on this window)")
hold = full.loc[HOLDOUT[0]:HOLDOUT[1]]
b100, res = table(f"2011-08-18 -> 2016-12-31  ({len(hold)} days)", hold)

print("\n[3] CRITERION CHECK")
c1 = res[100]["final"] > b100["final"]
c2 = res[100]["max_dd"] > b100["max_dd"]
c3 = res[100]["final"] > res[200]["final"] and res[100]["max_dd"] > res[200]["max_dd"]
print(f"    1. MA100 wealth > buy&hold          : {'PASS' if c1 else 'FAIL'}"
      f"  (${res[100]['final']:,.0f} vs ${b100['final']:,.0f})")
print(f"    2. MA100 drawdown < buy&hold        : {'PASS' if c2 else 'FAIL'}"
      f"  ({res[100]['max_dd']:.1f}% vs {b100['max_dd']:.1f}%)")
print(f"    3. MA100 beats MA200 on both        : {'PASS' if c3 else 'FAIL'}"
      f"  (MA200 ${res[200]['final']:,.0f} / {res[200]['max_dd']:.1f}%)")

print("\n[4] ROBUSTNESS INSIDE THE HOLDOUT")
t_cost = table("holdout at 0.2% per switch", hold, cost=0.002)
rc = run(hold, 100, 0.002)
t_lag = table("holdout with a 3-day execution delay", hold, delay=3)
rl = run(hold, 100, 0.0, 3)
print("\n  sub-blocks (MA100 versus buy & hold):")
wins = 0
for s, e in SUBBLOCKS:
    px = full.loc[s:e]
    b = bh(px); m = run(px, 100)
    win = m["final"] > b["final"]
    wins += win
    print(f"    {s} -> {e}: MA100 ${m['final']:>11,.0f} ({m['max_dd']:>6.1f}%)  "
          f"BH ${b['final']:>11,.0f} ({b['max_dd']:>6.1f}%)  {'WIN' if win else 'LOSS'}")
c4 = (rc["final"] > t_cost[0]["final"]) and (rl["final"] > t_lag[0]["final"]) and wins >= 2
print(f"    4. robustness                       : {'PASS' if c4 else 'FAIL'}"
      f"  (cost ${rc['final']:,.0f} vs BH ${t_cost[0]['final']:,.0f}; "
      f"lag ${rl['final']:,.0f} vs BH ${t_lag[0]['final']:,.0f}; {wins}/3 sub-blocks)")

print("\n" + "=" * 74)
passed = all([c1, c2, c3, c4])
print(f"VERDICT: {'PASS - the 100-day switch may become the execution rule' if passed else 'FAIL - the 100-day switch stays a hypothesis'}")
print(f"  criteria met: {sum([c1, c2, c3, c4])}/4")
print("=" * 74)
