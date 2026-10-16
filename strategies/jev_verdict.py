#!/usr/bin/env python3
"""PRE-REGISTERED VERDICT GATE for the JeV walk-forward trader.

Criteria are fixed BEFORE seeing the final sweep numbers, so the result
cannot be tuned after the fact. All five must hold for FEASIBLE:

  C1  the best mapping beats plain buy-and-hold BTC over the identical span
  C2  the best mapping beats the spot 200d-MA switch over the identical span
  C3  zero liquidations across all decisions
  C4  hit rate above 50 percent
  C5  bootstrap p < 0.20: random-direction entries at the same leverage and
      the same dates do not match the mapping's mean

Slippage and fee are re-charged at 5 bp + 1 bp per side inside the
recomputation, so a mapping that only works on zero-cost fills fails.

Reads every decision log in data/jev_decisions. Zero model calls.
Stdout only.

Run: .venv/bin/python strategies/jev_verdict.py
"""
import numpy as np
import pandas as pd

import jev_walkforward as J
from jev_leverage_map import MAPPINGS, load_rows, run_mapping, curve_stats

FEE_BP = 6.0   # 5 bp taker + 1 bp slippage, per side
SEED = 7


def baselines(feats, dates):
    """Buy-and-hold and the spot 200d-MA switch over the decision span."""
    lo, hi = min(dates), max(dates)
    px = feats.loc[lo:hi, "close"]
    if len(px) < 2:
        return None, None
    bh = px.iloc[-1] / px.iloc[0] - 1
    ma = feats.loc[lo:hi, "ma200"]
    sig = (px > ma).shift(1).fillna(False)
    ret = px.pct_change().fillna(0.0)
    sw = float((1.0 + sig * ret).prod() - 1.0)
    return bh, sw


def cost_adjusted(feats, rows, fn):
    """Same mapping, but fees re-charged at FEE_BP with slippage included."""
    out = []
    for r in rows:
        t = pd.Timestamp(r["date"], tz="UTC")
        if t not in feats.index:
            continue
        lev = fn(r["decision"]["action"], r["risk"], r["conf"], r)
        act = r["decision"]["action"]
        pos = feats.index.get_loc(t)
        end = pos + r["horizon_days"]
        if end >= len(feats):
            continue
        entry, exit_ = feats["close"].iloc[pos], feats["close"].iloc[end]
        if act == "flat" or lev == 0:
            out.append({"net": 0.0, "lev": 0.0, "liq": False})
            continue
        ret = exit_ / entry - 1
        if act == "short":
            ret = -ret
        window = feats.iloc[pos + 1:end + 1]
        if act == "long":
            adverse = entry / window["low"].min() - 1
        else:
            adverse = window["high"].max() / entry - 1
        if adverse >= 1.0 / lev - J.MM:
            out.append({"net": -100.0, "lev": lev, "liq": True})
            continue
        days = max(1, (feats.index[end] - feats.index[pos]).days)
        fr = feats["funding7"].iloc[pos]
        funding = 0.0 if np.isnan(fr) else fr * days * lev * (1 if act == "long" else -1)
        net = lev * ret - 2 * (FEE_BP / 1e4) * lev - funding
        out.append({"net": net * 100, "lev": lev, "liq": False})
    return out


def bootstrap_p(feats, rows, res, draws=2000):
    """Chance that random direction at the same leverage matches the mean."""
    rng = np.random.default_rng(SEED)
    real = np.mean([r["net"] for r in res]) if res else 0.0
    pool = []
    for r in rows:
        t = pd.Timestamp(r["date"], tz="UTC")
        if t not in feats.index:
            continue
        pos = feats.index.get_loc(t)
        end = pos + r["horizon_days"]
        if end >= len(feats):
            continue
        pool.append((feats["close"].iloc[end] / feats["close"].iloc[pos] - 1.0,
                     r["decision"]["action"]))
    if not pool:
        return 1.0
    means = []
    for _ in range(draws):
        acc = []
        for ret, act in pool:
            if act == "flat":
                acc.append(0.0)
                continue
            lev = 1.0
            sgn = 1 if rng.random() < 0.5 else -1
            acc.append(100 * (lev * sgn * ret - 2 * (FEE_BP / 1e4) * lev))
        means.append(np.mean(acc))
    means = np.array(means)
    return float(np.mean(means >= real))


def main():
    feats = J.build_features()
    rows = load_rows()
    risks = [r for r in rows if r["risk"] is not None]
    print("=== JEV WALK-FORWARD VERDICT GATE (pre-registered) ===")
    print(f"decisions: {len(rows)} | with jev risk score: {len(risks)}")
    if not risks:
        print("VERDICT: INSUFFICIENT DATA - no decisions logged yet")
        return
    dates = [pd.Timestamp(r["date"], tz="UTC") for r in risks]
    bh, sw = baselines(feats, dates)
    print(f"span: {min(dates).date()} -> {max(dates).date()} | "
          f"buy-and-hold {bh*100:+.1f}% | spot MA200 switch {sw*100:+.1f}%")
    print(f"costs charged: {FEE_BP} bp per side (5 taker + 1 slippage)\n")

    header = ("{:<34} {:>4} {:>9} {:>7} {:>6} {:>8} {:>4} {:>6}".format(
        "mapping", "n", "compound", "mean%", "hit%", "worstDD", "liq", "p"))
    print(header)
    results = {}
    for name, fn in MAPPINGS:
        res = cost_adjusted(feats, risks, fn)
        if not res:
            continue
        eq, dd = curve_stats(res)
        nets = [r["net"] for r in res]
        hit = 100 * sum(1 for n in nets if n > 0) / len(nets)
        liqs = sum(1 for r in res if r["liq"])
        p = bootstrap_p(feats, risks, res)
        results[name] = dict(eq=eq, dd=dd, hit=hit, liq=liqs, p=p, n=len(res))
        print(f"{name:34} {len(res):>4} {eq:>8.2f}x {np.mean(nets):>+7.2f} "
              f"{hit:>6.1f} {dd*100:>7.1f}% {liqs:>4} {p:>6.3f}")

    if not results:
        print("VERDICT: INSUFFICIENT DATA")
        return
    best = max(results.items(), key=lambda kv: kv[1]["eq"])
    n, m = best
    checks = [
        ("C1 beats buy-and-hold", m["eq"] - 1 > bh),
        ("C2 beats spot MA200 switch", m["eq"] - 1 > sw),
        ("C3 zero liquidations", m["liq"] == 0),
        ("C4 hit rate above 50%", m["hit"] > 50),
        ("C5 bootstrap p < 0.20", m["p"] < 0.20),
    ]
    print(f"\nbest mapping: {n} ({m['eq']:.2f}x, {m['hit']:.1f}% hit, "
          f"{m['liq']} liqs, p={m['p']:.3f})")
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    passed = all(ok for _, ok in checks)
    print(f"\nVERDICT: {'FEASIBLE' if passed else 'NOT FEASIBLE'} - "
          f"{sum(1 for _, ok in checks if ok)}/{len(checks)} criteria pass")


if __name__ == "__main__":
    main()
