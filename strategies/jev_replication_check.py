#!/usr/bin/env python3
"""REPLICATION CHECK: does the direction edge survive a second sampling?

The model is not deterministic, so a single walk-forward pass cannot tell
an edge from a lucky draw. This compares two independent passes over the
identical dates:

  run 1 = data/jev_decisions/shard_0*.jsonl
  run 2 = data/jev_decisions/repl_*.jsonl

If the directional hit rate holds near its run 1 value, the read is real.
If it collapses to a coin flip, run 1 was noise.

Stdout only. Run: .venv/bin/python strategies/jev_replication_check.py
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import jev_walkforward as J

DIR = Path(__file__).parent.parent / "data" / "jev_decisions"


def load(pattern, exclude=()):
    rows = {}
    for path in sorted(DIR.glob(pattern)):
        if any(x in path.name for x in exclude):
            continue
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if not r.get("decision") or "outcome_pct" not in r:
                continue
            d = r["date"]
            if d not in rows:
                rows[d] = r
    return rows


def binomial_p(wins, n):
    if n == 0:
        return 1.0
    return min(1.0, sum(math.comb(n, k) for k in range(wins, n + 1)) / 2 ** n)


def stats(feats, rows, label):
    longs, shorts, flats = [], [], []
    for r in rows.values():
        t = pd.Timestamp(r["date"], tz="UTC")
        if t not in feats.index:
            continue
        pos = feats.index.get_loc(t)
        end = pos + r["horizon_days"]
        if end >= len(feats):
            continue
        ret = feats["close"].iloc[end] / feats["close"].iloc[pos] - 1.0
        {"long": longs, "short": shorts, "flat": flats}[
            r["decision"]["action"]].append(ret)
    n = len(longs) + len(shorts)
    w = sum(1 for r in longs if r > 0) + sum(1 for r in shorts if r < 0)
    hit = 100 * w / n if n else 0.0
    print(f"\n{label}")
    print(f"  calls: long {len(longs)} short {len(shorts)} flat {len(flats)}")
    print(f"  direction hit {hit:.1f}% ({w}/{n}) | binomial p = "
          f"{binomial_p(w, n):.4f}")
    if longs:
        print(f"  long  mean {np.mean(longs)*100:+.2f}%  win "
              f"{100*sum(1 for r in longs if r>0)/len(longs):.1f}%")
    if shorts:
        print(f"  short mean {np.mean(shorts)*100:+.2f}%  win "
              f"{100*sum(1 for r in shorts if r<0)/len(shorts):.1f}%")
    return hit, len(longs), len(shorts), w, n


def main():
    feats = J.build_features()
    r1 = load("shard_0*.jsonl")
    r2 = load("repl_*.jsonl")
    common = sorted(set(r1) & set(r2))
    print("=== REPLICATION CHECK ===")
    print(f"run 1 decisions: {len(r1)} | run 2 decisions: {len(r2)} | "
          f"shared dates: {len(common)}")

    h1 = stats(feats, {d: r1[d] for d in common}, "run 1 (original)")
    h2 = stats(feats, {d: r2[d] for d in common}, "run 2 (replication)")

    agree = sum(1 for d in common
                if r1[d]["decision"]["action"] == r2[d]["decision"]["action"])
    print(f"\ndecision agreement between runs: {agree}/{len(common)} = "
          f"{100*agree/len(common):.1f}% (a deterministic model would be 100%)")

    lev1 = [r1[d]["decision"]["leverage"] for d in common]
    lev2 = [r2[d]["decision"]["leverage"] for d in common]
    print(f"mean leverage run 1 {np.mean(lev1):.2f}x | run 2 "
          f"{np.mean(lev2):.2f}x")

    nets1 = [r1[d]["outcome_pct"] for d in common]
    nets2 = [r2[d]["outcome_pct"] for d in common]
    print(f"per-decision outcome correlation: {np.corrcoef(nets1, nets2)[0,1]:.3f}")

    print("\n=== VERDICT ON REPLICATION ===")
    if h2[0] > 52 and h2[4] > 100:
        print(f"direction edge REPLICATES: run 1 {h1[0]:.1f}% -> "
              f"run 2 {h2[0]:.1f}% (p={binomial_p(h2[3], h2[4]):.4f})")
    elif h2[0] > 50:
        print(f"direction edge WEAK: run 1 {h1[0]:.1f}% -> run 2 {h2[0]:.1f}%, "
              f"within noise")
    else:
        print(f"direction edge FAILS to replicate: run 1 {h1[0]:.1f}% -> "
              f"run 2 {h2[0]:.1f}%, run 1 was a lucky sampling")


if __name__ == "__main__":
    main()
