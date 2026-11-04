#!/usr/bin/env python3
"""
EXPOSURE HOLDOUT - pre-declared 2026-11-04 (third test: the only lever left)

The two switching tests failed to deliver a profit-zone floor. The drawdown-first test
showed every daily-close rule dipping below starting capital in 2011-2016. This script
tests the remaining lever: position size, i.e. a permanent cash sleeve.

FROZEN DESIGN
  Selection sample : 2017-01-01 .. 2026-11-01
  Holdout sample   : 2011-08-18 .. 2016-12-31

  Candidates: hold a fixed fraction w of the book in BTC, the rest in cash earning 0%.
    w = 1.00  is the current book (fully allocated, no switch)
    w = 0.75, 0.50, 0.25
  Each is tested WITHOUT a switch and WITH the 200-day switch on the BTC sleeve
  (the switch already proved it reduces drawdown on both windows).

  Metrics: final equity, worst peak-to-trough giveback, trough versus starting capital.

  DECISION RULE, frozen:
    A sleeve is "sufficient" if its giveback in BOTH windows is no worse than -50%,
    it never takes the book below 0.50x of starting capital, and its final equity is at
    least 0.35x of the fully-allocated buy-and-hold in the same window.
    Among sufficient sleeves, choose the one with the highest holdout final equity.
    If none is sufficient, say so and stop designing rules on this dataset.
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


def sleeve(px, w, switch):
    rets = px.pct_change().fillna(0)
    if switch:
        ma = px.rolling(200).mean()
        sig = (px >= ma).astype(float)
        sig[ma.isna()] = 1.0
        gate = sig.shift(1).fillna(1.0)
    else:
        gate = pd.Series(1.0, index=px.index)
    pos = w * gate
    eq = (1 + rets * pos).cumprod() * 10000
    return {"final": float(eq.iloc[-1]),
            "giveback": float((eq / eq.cummax() - 1).min() * 100),
            "trough": float(eq.min())}


px = btc()
print("=" * 78)
print("EXPOSURE HOLDOUT - pre-declared 2026-11-04")
print("=" * 78)
res = {}
for label, win in (("SELECTION 2017-2026", SELECTION), ("HOLDOUT 2011-2016", HOLDOUT)):
    p = px.loc[win[0]:win[1]]
    print(f"\n  {label}   (buy&hold reference: ${sleeve(p,1.0,False)['final']:,.0f}, "
          f"{sleeve(p,1.0,False)['giveback']:.1f}%)")
    print(f"    {'sleeve':22s} {'final':>13s} {'giveback':>10s} {'trough/cost':>12s}")
    for w in (1.0, 0.75, 0.5, 0.25):
        for sw in (False, True):
            r = sleeve(p, w, sw)
            res[(label, w, sw)] = r
            name = f"{int(w*100)}% BTC" + (" + 200d" if sw else "")
            print(f"    {name:22s} ${r['final']:>12,.0f} {r['giveback']:>9.1f}% "
                  f"{r['trough']/10000:>11.2f}x")

print("\n  DECISION RULE")
ok = []
bh_sel = res[("SELECTION 2017-2026", 1.0, False)]["final"]
bh_hold = res[("HOLDOUT 2011-2016", 1.0, False)]["final"]
for w in (1.0, 0.75, 0.5, 0.25):
    for sw in (False, True):
        s = res[("SELECTION 2017-2026", w, sw)]
        h = res[("HOLDOUT 2011-2016", w, sw)]
        c1 = s["giveback"] >= -50 and h["giveback"] >= -50
        c2 = s["trough"] >= 5000 and h["trough"] >= 5000
        c3 = s["final"] >= 0.35 * bh_sel and h["final"] >= 0.35 * bh_hold
        good = c1 and c2 and c3
        if good:
            ok.append((h["final"], w, sw))
        name = f"{int(w*100)}% BTC" + (" + 200d" if sw else "")
        print(f"    {name:22s} giveback {s['giveback']:>6.1f}/{h['giveback']:>6.1f}  "
              f"trough {s['trough']/10000:>4.2f}x/{h['trough']/10000:>4.2f}x  "
              f"final {s['final']/bh_sel:>4.2f}x/{h['final']/bh_hold:>4.2f}x  "
              f"{'PASS' if good else ''}")

print("\n" + "=" * 78)
if ok:
    best = max(ok)
    print(f"VERDICT: PASS -> {int(best[1]*100)}% BTC" + (" + 200d switch" if best[2] else ""))
    print("  is the largest holdout equity that holds the frozen criteria in both windows.")
else:
    print("VERDICT: FAIL -> no sleeve on this dataset meets the frozen criteria")
print("=" * 78)
