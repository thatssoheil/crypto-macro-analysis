#!/usr/bin/env python3
"""
ON-CHAIN CONFIDENCE GATE (stateless: prints, saves nothing)

The live Glassnode series is a CURRENT best estimate; entity labelling is revised
retroactively, so a flow number read today can differ from the same number as it was
known at the time. Every gn_* chart therefore has a point-in-time twin. This script
compares each pair over the committed window and prints a verdict, so a flow read
carries its own confidence instead of assuming it.

Measured 2026-09-12 (why this exists): BTC daily netflow differed from its PIT twin on
30/30 days - mean 232%, max 1,150%, one sign flip, and the 7-day sum flipped sign
(+4,904 live vs -19,494 pit). ETH agreed to 0.2%. Same vendor, same metric, opposite
reliability: it is per-metric-per-window and only a mechanical check can tell you which.

Rules (conventions, NOT outcome-validated - they gate description, not prophecy):
  flow  (netflow):  CONFIRMED     sign agreement >= 80% and 7d sums share a sign
                    UNSTABLE      otherwise, while disagreement stays under 60%
                    CONTRADICTED  sign agreement < 60%, or the 7d sums differ in sign
  level (balance, SOPR, NUPL, supply in profit):
                    CONFIRMED     mean daily diff <= 1% and latest diff <= 1%
                    UNSTABLE      <= 5%
                    CONTRADICTED  > 5%

Exit code 0 always: this is a report, not a build gate. The verdicts land in the daily
heartbeat and the weekly summary.
"""
import sys
from pathlib import Path
import pandas as pd

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"

# concept -> (live chart, pit chart, kind)
PAIRS = {}
for asset in ("btc", "eth"):
    sfx = "" if asset == "btc" else "_eth"
    PAIRS[f"{asset.upper()} netflow"] = (f"gn_exchange_netflow_{asset}", f"gn_exchange_netflow_{asset}_pit", "flow")
    PAIRS[f"{asset.upper()} exchange_bal"] = (f"gn_exchange_balance_{asset}", f"gn_exchange_balance_{asset}_pit", "level")
    PAIRS[f"{asset.upper()} SOPR"] = (f"gn_sopr{sfx}", f"gn_sopr{sfx}_pit", "level")
    PAIRS[f"{asset.upper()} NUPL"] = (f"gn_nupl{sfx}", f"gn_nupl{sfx}_pit", "level")
    PAIRS[f"{asset.upper()} profit%"] = (f"gn_supply_in_profit_pct{sfx}", f"gn_supply_in_profit_pct{sfx}_pit", "level")


def load(name):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()["value"].astype(float)


def verdict(kind, live, pit):
    common = live.index.intersection(pit.index)
    if len(common) < 4:
        return "NO-DATA", {}, common
    a, b = live.loc[common], pit.loc[common]
    if kind == "flow":
        sign_agree = (a.gt(0) == b.gt(0)).mean() * 100
        s7a, s7b = a.tail(7).sum(), b.tail(7).sum()
        same_sign = (s7a > 0) == (s7b > 0)
        if sign_agree >= 80 and same_sign:
            v = "CONFIRMED"
        elif sign_agree < 60 or not same_sign:
            v = "CONTRADICTED"
        else:
            v = "UNSTABLE"
        return v, {"sign_agree": sign_agree, "s7a": s7a, "s7b": s7b, "s30a": a.sum(), "s30b": b.sum()}, common
    rel = ((a - b).abs() / b.abs().replace(0, float("nan"))).dropna() * 100
    mean_rel = rel.mean() if len(rel) else 0.0
    last_rel = abs(a.iloc[-1] - b.iloc[-1]) / (abs(b.iloc[-1]) or 1) * 100
    if mean_rel <= 1 and last_rel <= 1:
        v = "CONFIRMED"
    elif mean_rel <= 5 and last_rel <= 5:
        v = "UNSTABLE"
    else:
        v = "CONTRADICTED"
    return v, {"mean_rel": mean_rel, "last_rel": last_rel, "last_a": a.iloc[-1], "last_b": b.iloc[-1]}, common


rows, tally, machine = [], {}, []
for label, (live_name, pit_name, kind) in PAIRS.items():
    live, pit = load(live_name), load(pit_name)
    if live is None or pit is None:
        rows.append((label, "NO-DATA", f"missing chart ({live_name if live is None else pit_name})"))
        tally["NO-DATA"] = tally.get("NO-DATA", 0) + 1
        machine.append(f"GATE {label.lower().replace(' ', '_')} NO-DATA")
        continue
    v, m, common = verdict(kind, live, pit)
    tally[v] = tally.get(v, 0) + 1
    key = label.lower().replace(" ", "_")
    if kind == "flow":
        machine.append(f"GATE {key} {v} live_7d={m['s7a']:.0f} pit_7d={m['s7b']:.0f} sign={m['sign_agree']:.0f}")
    else:
        machine.append(f"GATE {key} {v} last_delta_pct={m['last_rel']:.2f} mean_delta_pct={m['mean_rel']:.2f}")
    if kind == "flow":
        detail = (f"live 7d {m['s7a']:+,.0f} / 30d {m['s30a']:+,.0f} | pit 7d {m['s7b']:+,.0f} / 30d {m['s30b']:+,.0f}"
                  f" | daily sign agreement {m['sign_agree']:.0f}%"
                  f" | 7d delta {abs(m['s7a']-m['s7b'])/max(abs(m['s7b']),1)*100:.0f}%")
    else:
        detail = (f"latest live {m['last_a']:,.4f} vs pit {m['last_b']:,.4f} ({m['last_rel']:.2f}%)"
                  f" | mean daily diff {m['mean_rel']:.2f}%")
    rows.append((label, v, detail))

print("=" * 78)
print("ON-CHAIN CONFIDENCE (live vs point-in-time, committed window)")
print("=" * 78)
for label, v, detail in rows:
    print(f"  [{v:13s}] {label:20s} {detail}")
    if v == "CONTRADICTED":
        print(f"      -> do NOT state a {label.split()[1]} direction from the live series alone;"
              f" use the PIT series for anything tested, and re-check before acting.")
order = ["CONFIRMED", "UNSTABLE", "CONTRADICTED", "NO-DATA"]
summary = ", ".join(f"{tally.get(k, 0)} {k.lower()}" for k in order if tally.get(k))
print()
print(f"  ONCHAIN CONFIDENCE: {summary}")
bad = [r[0] for r in rows if r[1] in ("CONTRADICTED", "NO-DATA")]
print(f"  FLAGGED: {', '.join(bad) if bad else 'none'}")
print()
for line in machine:          # machine-readable, no indent: grepped by the cron jobs
    print(line)
flagged = f" | flagged: {', '.join(bad)}" if bad else ""
print(f"ONCHAIN SUMMARY: {summary}{flagged}")
sys.exit(0)
