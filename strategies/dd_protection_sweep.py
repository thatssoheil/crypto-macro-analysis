#!/usr/bin/env python3
"""
DD-PROTECTION SWEEP: which exit layer(s) actually cap your experienced drawdown?
Strategies (all re-enter on close above 200d MA unless noted):
  1. buy-hold
  2. 200d MA (current baseline)
  3. 100d MA (faster)
  4. 50d MA (fastest)
  5. 200d MA OR DD -25% from ATH (circuit breaker)
  6. 200d MA OR DD -20% from ATH
  7. 200d MA OR DD -15% from ATH
  8. 50d MA OR DD -20% (fast + breaker)
  9. 100/200 death-cross exit, golden-cross re-entry

Measures: final value, max DD experienced (the number that matters to the user),
avg DD at exit (how much of the drop you eat before the exit fires), #exits,
days in market. Daily close data, no costs (caveat: gap risk in real life).
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"
OUT = Path(__file__).parent.parent / "data" / "macro"

btc = pd.read_csv(DATA / "btcusd_daily_bitstamp.csv")
btc["ts"] = pd.to_datetime(btc["ts"], utc=True)
btc = btc.set_index("ts").sort_index()["close"]

def simulate(exit_rule, reentry_rule, label):
    """exit_rule(dd_from_ath, px, ma_vals) -> bool exit. reentry_rule -> bool re-enter."""
    ma200 = btc.rolling(200).mean()
    ma100 = btc.rolling(100).mean()
    ma50 = btc.rolling(50).mean()
    ath = 0.0
    in_mkt = True
    exits = 0
    dd_at_exit = []
    eq = np.empty(len(btc))
    eq[0] = 10000.0
    for i in range(1, len(btc)):
        px = btc.iloc[i]
        ath = max(ath, px)
        dd = px / ath - 1
        if in_mkt:
            if exit_rule(dd, px, ma200.iloc[i], ma100.iloc[i], ma50.iloc[i]):
                in_mkt = False
                exits += 1
                dd_at_exit.append(dd * 100)
        else:
            if reentry_rule(0.0, px, ma200.iloc[i], ma100.iloc[i], ma50.iloc[i]):
                in_mkt = True
        ret = btc.iloc[i] / btc.iloc[i-1] - 1
        eq[i] = eq[i-1] * (1 + ret if in_mkt else 1.0)
    eq = pd.Series(eq, index=btc.index)
    dd = (eq / eq.cummax() - 1).min() * 100
    return {
        "label": label,
        "final": float(eq.iloc[-1]),
        "pct": float((eq.iloc[-1] / 10000 - 1) * 100),
        "max_dd": float(dd),
        "avg_dd_at_exit": float(np.mean(dd_at_exit)) if dd_at_exit else 0.0,
        "worst_dd_at_exit": float(min(dd_at_exit)) if dd_at_exit else 0.0,
        "exits": exits,
        "days_in_mkt": int(in_mkt_hist := (eq.diff() != 0).sum()),  # approx
    }

def never(dd, px, m200, m100, m50): return False
def below(dd, px, m200, m100, m50): return not np.isnan(m200) and px < m200
def below100(dd, px, m200, m100, m50): return not np.isnan(m100) and px < m100
def below50(dd, px, m200, m100, m50): return not np.isnan(m50) and px < m50
def above(dd, px, m200, m100, m50): return not np.isnan(m200) and px > m200
def above50(dd, px, m200, m100, m50): return not np.isnan(m50) and px > m50
def dd25(dd, px, m200, m100, m50): return dd < -0.25
def dd20(dd, px, m200, m100, m50): return dd < -0.20
def dd15(dd, px, m200, m100, m50): return dd < -0.15
def comb(dd, px, m200, m100, m50, thr):
    return (not np.isnan(m200) and px < m200) or dd < -thr

def mk_comb(thr):
    return (lambda dd, px, m200, m100, m50: comb(dd, px, m200, m100, m50, thr))

def cross_exit(dd, px, m200, m100, m50): return not np.isnan(m100) and not np.isnan(m200) and m100 < m200
def cross_entry(dd, px, m200, m100, m50): return not np.isnan(m100) and not np.isnan(m200) and m100 > m200

def comb50(dd, px, m200, m100, m50):
    return (not np.isnan(m50) and px < m50) or dd < -0.20

STRATS = [
    ("buy-hold",              never,    never),
    ("200d MA",               below,    above),
    ("100d MA",               below100, above),
    ("50d MA",                below50,  above50),
    ("200d MA OR DD-25%",     mk_comb(0.25), above),
    ("200d MA OR DD-20%",     mk_comb(0.20), above),
    ("200d MA OR DD-15%",     mk_comb(0.15), above),
    ("50d MA OR DD-20%",      comb50,   above50),
    ("100/200 cross",         cross_exit, cross_entry),
]

print("=== DD-PROTECTION SWEEP (2011-2026, $10k start, daily closes) ===\n")
results = []
for label, ex, re_ in STRATS:
    r = simulate(ex, re_, label)
    results.append(r)
    print(f"  {label:22s} final ${r['final']:>14,.0f} ({r['pct']:>+10,.0f}%)  "
          f"maxDD {r['max_dd']:>6.1f}%  avgDD@exit {r['avg_dd_at_exit']:>6.1f}%  "
          f"worstDD@exit {r['worst_dd_at_exit']:>6.1f}%  exits {r['exits']:>3d}")

with open(OUT / "dd_protection_sweep.json", "w") as f:
    json.dump(results, f, indent=2)
print(f"\nSaved -> {OUT/'dd_protection_sweep.json'}")
