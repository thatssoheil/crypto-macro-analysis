#!/usr/bin/env python3
"""JEV RISK SCORE AS THE LEVERAGE SETTER - zero new model calls.

The walk-forward log already stores, for every decision, jev's own triage
risk score (inside the reason string, e.g. "jev:high/risk=0.40/conf=0.13")
plus the direction the answering model chose. This script holds the
DIRECTION fixed and re-sizes the trade six different ways, including
"let jev's risk score pick the leverage" - the owner's idea.

Costs are identical to the walk-forward: 5 bp per side, funding on
notional, exact wick liquidation at mm = 0.5 percent. Forward returns are
recomputed from the price data, so any leverage can be applied to the
same decision. Results print to stdout (stateless).

Run: cd /root/hermes-projects/crypto-macro-analysis
     .venv/bin/python strategies/jev_leverage_map.py
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

import jev_walkforward as J

LOGFILE = Path(__file__).parent.parent / "data" / "jev_decisions" / "decisions.jsonl"
LOGDIR = LOGFILE.parent
MAXLEV = 10.0


def parse_risk(reason):
    m = re.search(r"risk=([\d.]+)", reason or "")
    return float(m.group(1)) if m else None


def parse_conf(reason):
    m = re.search(r"conf=([\d.]+)", reason or "")
    return float(m.group(1)) if m else None


def lev_model(action, risk, conf, row):
    """Baseline: whatever leverage the answering model chose."""
    return row["decision"]["leverage"]


def _fixed(k):
    return lambda action, risk, conf, row: (0.0 if action == "flat" else k)


def lev_risk_linear(action, risk, conf, row):
    if action == "flat" or risk is None:
        return 0.0
    return float(np.clip(MAXLEV * (1.0 - risk), 0.0, MAXLEV))


def lev_risk_halving(action, risk, conf, row):
    """Owner's bisect: start at max, halve once per risk band."""
    if action == "flat" or risk is None:
        return 0.0
    lev = MAXLEV
    for band in (0.20, 0.30, 0.40, 0.50):
        if risk >= band:
            lev /= 2.0
    return float(max(round(lev * 4) / 4, 0.25))


def lev_risk_tiers(action, risk, conf, row):
    if action == "flat" or risk is None:
        return 0.0
    if risk < 0.25:
        return 3.0
    if risk < 0.40:
        return 2.0
    if risk < 0.60:
        return 1.0
    return 0.0


def lev_longonly_1x(action, risk, conf, row):
    """The direction read, longs only, no shorts, no flats, 1x."""
    return 1.0 if action == "long" else 0.0


def lev_longonly_halving(action, risk, conf, row):
    if action != "long" or risk is None:
        return 0.0
    return lev_risk_halving(action, risk, conf, row)


def lev_longonly_tiers(action, risk, conf, row):
    if action != "long" or risk is None:
        return 0.0
    return lev_risk_tiers(action, risk, conf, row)


MAPPINGS = [
    ("A model-chosen (baseline)", lev_model),
    ("B fixed 1x", _fixed(1.0)),
    ("C fixed 2x", _fixed(2.0)),
    ("D jev-risk linear 10*(1-risk)", lev_risk_linear),
    ("E jev-risk halving (owner bisect)", lev_risk_halving),
    ("F jev-risk tiers 3/2/1/0", lev_risk_tiers),
    ("G longs-only fixed 1x", lev_longonly_1x),
    ("H longs-only halving", lev_longonly_halving),
    ("I longs-only tiers", lev_longonly_tiers),
]


def load_rows():
    """Read every decision log, keeping ONE cadence so dates do not double count.

    Earlier runs used a 5-day horizon and the dense shards use 3, so a naive
    read counts the same date twice under two horizons and inflates n. We
    keep only the most common horizon (the dense shard cadence once the
    shards dominate), then dedupe by date. Ledger files are skipped.
    """
    from collections import Counter
    raw = []
    for path in sorted(LOGDIR.glob("*.jsonl")):
        if "ledger" in path.name:
            continue
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not r.get("decision") or "outcome_pct" not in r:
                continue
            r["risk"] = parse_risk(r.get("reason"))
            r["conf"] = parse_conf(r.get("reason"))
            raw.append(r)
    if not raw:
        return []
    modal = Counter(r.get("horizon_days") for r in raw).most_common(1)[0][0]
    seen = set()
    rows = []
    for r in raw:
        if r.get("horizon_days") != modal:
            continue
        if r["date"] in seen:
            continue
        seen.add(r["date"])
        rows.append(r)
    rows.sort(key=lambda r: r["date"])
    return rows


def run_mapping(feats, rows, fn):
    results = []
    for r in rows:
        d = r["date"]
        t = pd.Timestamp(d, tz="UTC")
        if t not in feats.index:
            continue
        lev = fn(r["decision"]["action"], r["risk"], r["conf"], r)
        out = J.simulate(feats, t, r["decision"]["action"], lev, r["horizon_days"])
        if out is None:
            continue
        results.append({"snippet": r["snippet"], "net": out["net_pct"],
                        "lev": lev, "liq": out["liq"], "action": r["decision"]["action"]})
    return results


def curve_stats(res):
    eq = 1.0
    peak = 1.0
    dd = 0.0
    for r in res:
        eq *= max(0.0, 1 + r["net"] / 100)
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1)
    return eq, dd


def main():
    feats = J.build_features()
    rows = load_rows()
    risky = [r for r in rows if r["risk"] is not None]
    print(f"decisions in log: {len(rows)} | with a jev risk score: {len(risky)}")
    if not risky:
        print("no risk scores yet - run the walk-forward first")
        return
    snips = sorted({r["snippet"] for r in risky})
    print(f"snippets: {len(snips)} {snips}")

    print(f"\n{'mapping':34} {'n':>4} {'compound':>9} {'mean%':>7} {'hit%':>6} "
          f"{'worstDD':>8} {'avgLev':>7} {'liq':>4}")
    table = []
    for name, fn in MAPPINGS:
        res = run_mapping(feats, risky, fn)
        if not res:
            continue
        eq, dd = curve_stats(res)
        nets = [r["net"] for r in res]
        levs = [r["lev"] for r in res]
        liqs = sum(1 for r in res if r["liq"])
        hit = 100 * sum(1 for n in nets if n > 0) / len(nets)
        table.append((name, res))
        print(f"{name:34} {len(res):>4} {eq:>8.2f}x {np.mean(nets):>+7.2f} "
              f"{hit:>6.1f} {dd*100:>7.1f}% {np.mean(levs):>7.2f} {liqs:>4}")

    print("\nPer-snippet compound multiple (mapping x snippet):")
    header = f"{'snippet':22}" + "".join(f"{n.split()[0]:>10}" for n, _ in table)
    print(header)
    for s in snips:
        line = f"{s:22}"
        for _, res in table:
            sub = [r for r in res if r["snippet"] == s]
            if sub:
                eq, _ = curve_stats(sub)
                line += f"{eq:>9.2f}x"
            else:
                line += f"{'-':>10}"
        print(line)


if __name__ == "__main__":
    main()
