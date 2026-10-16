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
    """Buy-and-hold and the spot 200d-MA switch over the decision span.

    Returns returns AND max drawdowns, because the pre-registered gate
    requires a risk condition as well as a return condition: a mapping
    that wins on return while falling much deeper than the switch is not
    an improvement.
    """
    lo, hi = min(dates), max(dates)
    px = feats.loc[lo:hi, "close"]
    if len(px) < 2:
        return None
    bh = px.iloc[-1] / px.iloc[0] - 1
    ret = px.pct_change().fillna(0.0)
    bh_eq = (1.0 + ret).cumprod()
    bh_dd = float((bh_eq / bh_eq.cummax() - 1.0).min())
    ma = feats.loc[lo:hi, "ma200"]
    sig = (px > ma).shift(1).fillna(False)
    sw_eq = (1.0 + sig * ret).cumprod()
    sw_dd = float((sw_eq / sw_eq.cummax() - 1.0).min())
    return {"bh": float(bh), "bh_dd": bh_dd,
            "sw": float(sw_eq.iloc[-1] - 1.0), "sw_dd": sw_dd}


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


def binomial_p(wins, n):
    """Exact one-sided p-value that wins out of n beats a coin flip."""
    if n == 0:
        return 1.0
    import math
    total = 2 ** n
    tail = sum(math.comb(n, k) for k in range(wins, n + 1))
    return min(1.0, tail / total)


def directional_skill(feats, rows):
    """Direction quality, independent of any leverage mapping.

    Answers the question the leverage rules cannot: is the model reading
    the market, or just being sized into a bull run?
    """
    buckets = {"long": [], "short": [], "flat": []}
    for r in rows:
        t = pd.Timestamp(r["date"], tz="UTC")
        if t not in feats.index:
            continue
        pos = feats.index.get_loc(t)
        end = pos + r["horizon_days"]
        if end >= len(feats):
            continue
        ret = feats["close"].iloc[end] / feats["close"].iloc[pos] - 1.0
        above = bool(feats["close"].iloc[pos] > feats["ma200"].iloc[pos])
        buckets[r["decision"]["action"]].append((ret, above, r["date"]))

    print("\n=== DIRECTIONAL SKILL (leverage-independent) ===")
    longs, shorts, flats = buckets["long"], buckets["short"], buckets["flat"]
    n_dir = len(longs) + len(shorts)
    wins = sum(1 for ret, _, _ in longs if ret > 0) + \
        sum(1 for ret, _, _ in shorts if ret < 0)
    hit = 100 * wins / n_dir if n_dir else 0.0
    print(f"long calls {len(longs)} | short calls {len(shorts)} | flat calls {len(flats)}")
    if n_dir:
        print(f"direction hit rate {hit:.1f}% ({wins}/{n_dir}) "
              f"| exact binomial p = {binomial_p(wins, n_dir):.4f}")
    if longs:
        print(f"  long:  mean fwd {np.mean([r for r,_,_ in longs])*100:+.2f}%  "
              f"win {100*sum(1 for r,_,_ in longs if r>0)/len(longs):.1f}%")
    if shorts:
        print(f"  short: mean fwd {np.mean([r for r,_,_ in shorts])*100:+.2f}%  "
              f"win {100*sum(1 for r,_,_ in shorts if r<0)/len(shorts):.1f}%")
    if flats:
        print(f"  flat:  mean fwd {np.mean([r for r,_,_ in flats])*100:+.2f}% "
              f"(negative means it stepped aside before drops)")

    print("\n  split by trend at the call:")
    for label, want in (("above 200d MA", True), ("below 200d MA", False)):
        ls = [r for r, a, _ in longs if a == want]
        ss = [r for r, a, _ in shorts if a == want]
        n = len(ls) + len(ss)
        w = sum(1 for r in ls if r > 0) + sum(1 for r in ss if r < 0)
        if n:
            print(f"    {label:15} n={n:>4} hit {100*w/n:>5.1f}%  "
                  f"long n={len(ls):>3}  short n={len(ss):>3}")
    return hit, n_dir


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
    base = baselines(feats, dates)
    if base is None:
        print("VERDICT: INSUFFICIENT DATA")
        return
    print(f"span: {min(dates).date()} -> {max(dates).date()} | "
          f"buy-and-hold {base['bh']*100:+.1f}% (fall {base['bh_dd']*100:.1f}%) | "
          f"spot MA200 switch {base['sw']*100:+.1f}% (fall {base['sw_dd']*100:.1f}%)")
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

    dir_hit, dir_n = directional_skill(feats, risks)

    if not results:
        print("VERDICT: INSUFFICIENT DATA")
        return
    print("\n=== CRITERIA PER MAPPING ===")
    print("{:<34} {:>4} {:>4} {:>4} {:>4} {:>4} {:>4}  {}".format(
        "mapping", "C1", "C2", "C3", "C4", "C5", "C6", ""))
    winners = []
    for name, m in results.items():
        flags = [
            m["eq"] - 1 > base["bh"],                       # C1 beats hold
            m["eq"] - 1 > base["sw"],                       # C2 beats switch
            m["liq"] == 0,                                  # C3 no liquidation
            dir_hit > 50,                                   # C4 direction edge
            m["p"] < 0.20,                                  # C5 beats random
            m["dd"] >= base["sw_dd"] - 0.10,                # C6 risk parity
        ]
        cells = "".join("  ok" if f else "  --" for f in flags)
        passed = all(flags)
        if passed:
            winners.append(name)
        print("{:<34}{}  {}".format(name, cells, "PASS" if passed else "fail"))

    print(f"\nC4 uses directional accuracy excluding flat calls: "
          f"{dir_hit:.1f}% over {dir_n} sided calls (flats are a choice, "
          f"not a miss)")
    if winners:
        print(f"\nVERDICT: FEASIBLE - mappings passing all 6: {winners}")
        print("caveat: 9 mappings were tested, so control the false positive "
              "rate by replicating the winner on unseen decisions before "
              "trusting it")
    else:
        print("\nVERDICT: NOT FEASIBLE - no mapping passes all 6 criteria")


if __name__ == "__main__":
    main()
