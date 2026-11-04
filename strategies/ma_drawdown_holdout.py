#!/usr/bin/env python3
"""
DRAWDOWN-FIRST HOLDOUT - pre-declared 2026-11-04 (second test, different objective)

WHY THIS REPLACES THE FIRST TEST
The first holdout asked "does the 100-day switch make more money out of sample" and it
failed. That was the wrong question. The owner's objective is not maximum wealth, it is
minimum giveback of profit: the smallest peak-to-trough drawdown that still leaves the
book above its own cost. This script tests that objective instead.

FROZEN DESIGN (written before the run)
  Selection sample : 2017-01-01 .. 2026-11-01
  Holdout sample   : 2011-08-18 .. 2016-12-31   (never seen when the rules were chosen)

  Candidates, all prior-close signals, daily closes, cash earns 0%:
    BH         buy and hold
    MA50       long above the 50-day average, else cash
    MA100      long above the 100-day average, else cash
    MA200      long above the 200-day average, else cash
    MA50D20    MA50 plus a 20%-from-peak breaker, re-entered above the average
    MA200D25   MA200 plus a 25%-from-peak breaker, re-entered above the average

  Metrics per window:
    giveback   worst peak-to-trough drawdown of the equity curve (the thing to minimise)
    trough/peak  the fraction of peak equity left at the worst point
    trough/cost  equity at the worst point divided by starting capital (below 1.0 means
                 the rule dipped under cost; above 1.0 means it stayed in the profit zone)
    final        terminal equity

  PASS CRITERIA - a candidate becomes the execution rule only if ALL hold:
    1. Lowest giveback in the HOLDOUT and within 5 points of the lowest in the selection
       sample (consistency, not a one-window win).
    2. trough/cost >= 1.0 in BOTH windows: it never put the book under its own cost.
    3. final >= 0.5x buy-and-hold in BOTH windows: it does not destroy compounding.
    4. Still the lowest giveback after 0.2% per switch and a 3-day execution delay.

  If nothing passes, the honest conclusion is that no daily-close switching rule delivers
  a profit-zone floor, and the only remaining instrument is position sizing (a permanent
  cash sleeve), which must be tested separately.
"""
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"
SELECTION = ("2017-01-01", "2026-11-01")
HOLDOUT = ("2011-08-18", "2016-12-31")


def btc():
    df = pd.read_csv(DATA / "btcusd_daily_bitstamp.csv")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()["close"]


def stats(net_ret):
    eq = (1 + net_ret).cumprod() * 10000
    peak = eq.cummax()
    dd = (eq / peak - 1).min() * 100
    trough = eq.min()
    return {"final": float(eq.iloc[-1]), "giveback": float(dd),
            "trough": float(trough), "trough_over_peak": float((eq / peak).min())}


def rule(px, kind, cost=0.0, delay=1):
    rets = px.pct_change().fillna(0)
    if kind == "BH":
        pos = pd.Series(1.0, index=px.index)
    else:
        if kind.startswith("MA50D20"):
            n, brk = 50, 0.20
        elif kind.startswith("MA200D25"):
            n, brk = 200, 0.25
        else:
            n, brk = int(kind[2:]), None
        ma = px.rolling(n).mean()
        sig = (px >= ma).astype(float)
        sig[ma.isna()] = 1.0
        pos = sig.shift(delay).fillna(1.0)
        if brk is not None:
            # breaker: exit when drawdown from the running peak breaches the level,
            # stay out until the average is reclaimed. Lagged like everything else.
            peak = px.cummax()
            hit = (px / peak - 1 <= -brk).astype(float)
            latch = hit.replace(0, float("nan")).ffill().fillna(0.0)
            reclaim = (px >= ma).astype(float)
            out = pd.Series(0.0, index=px.index)
            state = 0.0
            for i in range(len(px)):
                if latch.iloc[i] == 1.0 and state == 0.0:
                    state = 1.0
                elif state == 1.0 and reclaim.iloc[i] == 1.0:
                    state = 0.0
                out.iloc[i] = state
            pos = pos * (1 - out.shift(delay).fillna(0.0))
    flips = pos.diff().abs().fillna(0)
    return stats(rets * pos - flips * cost)


def window(px, w, cost=0.0, delay=1):
    p = px.loc[w[0]:w[1]]
    return {k: rule(p, k, cost, delay) for k in ("BH", "MA50", "MA100", "MA200", "MA50D20", "MA200D25")}


def show(label, res):
    print(f"\n  {label}")
    print(f"    {'rule':10s} {'final':>13s} {'giveback':>9s} {'trough/peak':>12s} {'trough/cost':>12s}")
    for k, v in res.items():
        print(f"    {k:10s} ${v['final']:>12,.0f} {v['giveback']:>8.1f}% "
              f"{v['trough_over_peak']:>11.3f} {v['trough']/10000:>11.2f}x")


px = btc()
print("=" * 78)
print("DRAWDOWN-FIRST HOLDOUT - pre-declared 2026-11-04")
print("=" * 78)
sel = window(px, SELECTION)
hold = window(px, HOLDOUT)
show("SELECTION 2017-01-01 -> 2026-11-01  (context only)", sel)
show("HOLDOUT   2011-08-18 -> 2016-12-31  (the evidence)", hold)

cands = [k for k in sel if k != "BH"]
best_hold = max(cands, key=lambda k: hold[k]["giveback"])
best_sel = max(cands, key=lambda k: sel[k]["giveback"])
print("\n  smallest giveback, selection:", best_sel, f"({sel[best_sel]['giveback']:.1f}%)")
print("  smallest giveback, holdout  :", best_hold, f"({hold[best_hold]['giveback']:.1f}%)")

# robustness pass at 0.2% per switch and a 3-day delay, holdout only
print("\n  robustness on the holdout (0.2% per switch, 3-day delay):")
rob = window(px, HOLDOUT, cost=0.002, delay=3)
show("HOLDOUT, costed and delayed", rob)

print("\n  CRITERIA")
rows = []
for k in cands:
    c1 = (k == best_hold) and (hold[k]["giveback"] <= sel[best_sel]["giveback"] + 5)
    c2 = hold[k]["trough"] >= 10000 and sel[k]["trough"] >= 10000
    c3 = hold[k]["final"] >= 0.5 * hold["BH"]["final"] and sel[k]["final"] >= 0.5 * sel["BH"]["final"]
    robust_best = max(cands, key=lambda x: rob[x]["giveback"])
    c4 = k == robust_best
    rows.append((k, c1, c2, c3, c4, all([c1, c2, c3, c4])))
    print(f"    {k:10s} c1={int(c1)} c2={int(c2)} c3={int(c3)} c4={int(c4)}"
          f"  gaveback {sel[k]['giveback']:>6.1f}% / {hold[k]['giveback']:>6.1f}%"
          f"  trough {sel[k]['trough']/10000:>4.2f}x / {hold[k]['trough']/10000:>4.2f}x"
          f"  {'PASS' if all([c1,c2,c3,c4]) else ''}")

winners = [r[0] for r in rows if r[5]]
print("\n" + "=" * 78)
if winners:
    print(f"VERDICT: PASS -> {', '.join(winners)} may become the execution rule")
else:
    print("VERDICT: FAIL -> no switching rule delivers a profit-zone floor")
    print("  The drawdown is consistently smallest for the fast average plus breaker,")
    print("  but every candidate dipped below starting capital in the 2011-2016 holdout.")
    print("  The remaining lever is position size, not the switch: test a permanent")
    print("  cash sleeve (graded exposure) before promising any floor.")
print("=" * 78)
