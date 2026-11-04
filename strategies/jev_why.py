#!/usr/bin/env python3
"""WHY - the arithmetic behind each conclusion in the jev futures study.

Every claim in the report is recomputed here from the two independent
825-decision runs, so each one can be checked or refuted rather than
taken on trust. Parts:

  1. long vs short outcome distributions (is the short side actually losing?)
  2. PnL decomposition at 1x: long-only / short-only / long+short
  3. the short tail: how bad the adverse moves are while short
  4. leverage survival math against BTC's real wick distribution
  5. the bull-market confound: does the long timing beat a matched random
     long-only book, or is it just being long in a rising decade
  6. what fraction of the gross edge is eaten by costs

Stdout only. Run: .venv/bin/python strategies/jev_why.py
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import jev_walkforward as J

DIR = Path(__file__).parent.parent / "data" / "jev_decisions"
FEE = 6.0 / 1e4          # per side
MM = 0.005


def load(pattern):
    rows = {}
    for path in sorted(DIR.glob(pattern)):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if not r.get("decision") or "outcome_pct" not in r:
                continue
            rows.setdefault(r["date"], r)
    return rows


def fwd(feats, r):
    t = pd.Timestamp(r["date"], tz="UTC")
    if t not in feats.index:
        return None
    pos = feats.index.get_loc(t)
    end = pos + r["horizon_days"]
    if end >= len(feats):
        return None
    return (feats["close"].iloc[end] / feats["close"].iloc[pos] - 1.0,
            pos, end, t)


def curve(pnls):
    eq, peak, dd = 1.0, 1.0, 0.0
    for p in pnls:
        eq *= max(0.0, 1.0 + p)
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1.0)
    return eq, dd


def desc(name, xs):
    a = np.array(xs)
    if len(a) == 0:
        return
    print(f"  {name:22} n={len(a):>4} mean {a.mean()*100:>+6.2f}%  "
          f"median {np.median(a)*100:>+6.2f}%  std {a.std()*100:>5.2f}%  "
          f"skew {float(pd.Series(a).skew()):>+5.2f}  "
          f"worst {a.min()*100:>+7.2f}%  best {a.max()*100:>+6.2f}%")


def main():
    feats = J.build_features()
    runs = {"run 1": load("shard_0*.jsonl"), "run 2": load("repl_*.jsonl")}
    print("=== WHY: the arithmetic behind each conclusion ===")

    for label, rows in runs.items():
        longs, shorts, flats = [], [], []
        for r in sorted(rows.values(), key=lambda x: x["date"]):
            f = fwd(feats, r)
            if f is None:
                continue
            ret, pos, end, t = f
            fr = feats["funding7"].iloc[pos]
            days = max(1, (feats.index[end] - feats.index[pos]).days)
            fund = 0.0 if np.isnan(fr) else fr * days
            act = r["decision"]["action"]
            rec = dict(action=act, ret=ret, fund=fund, date=r["date"])
            {"long": longs, "short": shorts, "flat": flats}[act].append(rec)

        print(f"\n---------- {label} ----------")
        print(f"PART 1: forward BTC return after each call "
              f"({len(longs)} long, {len(shorts)} short, {len(flats)} flat)")
        desc("after a LONG call", [x["ret"] for x in longs])
        desc("after a SHORT call", [x["ret"] for x in shorts])
        desc("after a FLAT call", [x["ret"] for x in flats])
        print("  note: for a short, a NEGATIVE forward return is the win, so "
              "the short mean is favourable on paper")

        print("\nPART 2: PnL at 1x, costs 6bp per side, funding included")
        def pnl(x, side):
            gross = x["ret"] if side == "long" else -x["ret"]
            fund = x["fund"] * (-1 if side == "long" else +1)  # long pays
            return gross - 2 * FEE - fund
        lo = [pnl(x, "long") for x in longs]
        sh = [pnl(x, "short") for x in shorts]
        mixed = sorted([(x["date"], pnl(x, x["action"]))
                        for x in longs + shorts], key=lambda z: z[0])
        mixed = [p for _, p in mixed]
        for nm, ps in (("long-only 1x", lo), ("short-only 1x", sh),
                       ("long+short 1x", mixed)):
            eq, dd = curve(ps)
            calmar = ((eq ** (1 / 6.8) - 1) / abs(dd)) if dd else float("nan")
            print(f"  {nm:16} n={len(ps):>4} total {eq:>9.2f}x  "
                  f"mean {np.mean(ps)*100:>+5.2f}%  maxDD {dd*100:>6.1f}%  "
                  f"Calmar {calmar:>5.2f}")

        print("\nPART 3: the short tail (adverse moves while short)")
        adverse_short = [(x["ret"]) for x in shorts]  # positive = BTC rose = bad
        for thr in (0.05, 0.10, 0.15, 0.20):
            n = sum(1 for r in adverse_short if r > thr)
            print(f"  BTC rose more than {thr*100:>4.0f}% during a short: "
                  f"{n:>3} of {len(shorts)} = {100*n/len(shorts):>4.1f}%")
        sq = [r for r in adverse_short if r > 0.10]
        if sq:
            print(f"  those squeezes average {np.mean(sq)*100:+.1f}% "
                  f"(worst {max(sq)*100:+.1f}%)")

    print("\n---------- PART 4: leverage survival, unconditional ---------")
    close, low, high = feats["close"], feats["low"], feats["high"]
    idx = [i for i in range(len(feats) - 3)]
    long_adv = [(close.iloc[i] / low.iloc[i + 1:i + 4].min() - 1) for i in idx]
    short_adv = [(high.iloc[i + 1:i + 4].max() / close.iloc[i] - 1)
                 for i in idx]
    print(f"  every 3-day window in the sample (n={len(idx)}):")
    print(f"  {'lev':>5} {'dies on':>9} {'long windows':>14} {'short windows':>15}")
    for L in (1, 2, 3, 5, 10):
        thr = 1.0 / L - MM
        pl = 100 * sum(1 for a in long_adv if a >= thr) / len(long_adv)
        ps = 100 * sum(1 for a in short_adv if a >= thr) / len(short_adv)
        print(f"  {L:>4}x {thr*100:>8.1f}% {pl:>13.2f}% {ps:>14.2f}%")
    print("  the short column is the kill switch: a 10x short dies on a "
          "9.5% up-wick")

    print("\n---------- PART 5: bull-market confound ---------")
    r1 = runs["run 1"]
    longs_r1 = [r for r in r1.values() if r["decision"]["action"] == "long"]
    n_long = len(longs_r1)

    def long_pnl(r):
        f = fwd(feats, r)
        if f is None:
            return None
        ret, pos, end, t = f
        fr = feats["funding7"].iloc[pos]
        days = max(1, (feats.index[end] - feats.index[pos]).days)
        fund = 0.0 if np.isnan(fr) else fr * days
        return ret - 2 * FEE - fund

    real_ps = [p for p in (long_pnl(r) for r in longs_r1) if p is not None]
    real_eq, real_dd = curve(real_ps)

    all_dates = sorted(r1)
    rng = np.random.default_rng(7)
    sims = []
    for _ in range(2000):
        pick = rng.choice(len(all_dates), size=n_long, replace=False)
        ps = [p for p in (long_pnl(r1[all_dates[i]]) for i in pick)
              if p is not None]
        eq, _ = curve(ps)
        sims.append(eq)
    sims = np.array(sims)
    print(f"  the model's {n_long} long calls timed: {real_eq:.2f}x "
          f"(maxDD {real_dd*100:.1f}%)")
    print(f"  {n_long} LONG-ONLY days picked at RANDOM from the same span: "
          f"median {np.median(sims):.2f}x, 5th {np.percentile(sims,5):.2f}x, "
          f"95th {np.percentile(sims,95):.2f}x")
    print(f"  percentile of the model's result among random books: "
          f"{100*np.mean(sims < real_eq):.1f}%")
    print("  always-long 1x over the span is buy-and-hold at "
          f"{feats['close'].iloc[-1]/feats['close'].iloc[0]:.2f}x")

    print("\n---------- PART 6: cost share of the gross edge ---------")
    r1l = [fwd(feats, r)[0] for r in longs_r1 if fwd(feats, r) is not None]
    gross = np.mean(r1l)
    print(f"  long gross edge per call: {gross*100:+.2f}%")
    print(f"  round-trip fee: {2*FEE*100:.2f}%  ->  "
          f"{100*2*FEE/gross:.0f}% of the gross edge")
    print(f"  add 3 days of funding at about 0.0485%/day in-market: "
          f"{3*0.000485*100:.2f}%  ->  {(3*0.000485+gross*0+2*FEE)/gross*100:.0f}% "
          f"of gross all-in")


if __name__ == "__main__":
    main()
