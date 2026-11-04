#!/usr/bin/env python3
"""
SIGNAL PARITY CHECK - added 2026-11-04

The audits found that audit_dataset.py never compares the signal vector the engine actually
emits, and that nothing asserts the deployed engine and the historical replay agree. This
script closes both gaps with an INDEPENDENT recomputation: it runs the live engine, parses
the (signal, value) table it prints, recomputes all 14 signals from the raw CSVs using the
documented rules, and compares.

Deliberate duplication: this is a checker, not a second engine. If someone changes a rule in
macro_regime_v3.py and not here, the check FAILS, which is the point - the deployed rule and
the checked rule must be the same rule. Exits nonzero on any mismatch.
"""
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "macro_dataset"
PY = str(ROOT / ".venv" / "bin" / "python")


def load(name, date_col="date", col=None):
    df = pd.read_csv(DATA / f"{name}.csv")
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.sort_values(date_col).set_index(date_col)
    if col is None:
        col = [c for c in df.columns if c not in ("open", "high", "low", "volume")][0]
    return df[col]


def slope(s, n=200):
    ma = s.rolling(n).mean().iloc[-1]
    cur = s.iloc[-1]
    return 1 if cur > ma else (-1 if cur < ma else 0)


def band(v, hi_good, lo_bad):
    """+1 at or above hi_good, -1 at or below lo_bad, else 0 (value-is-good direction)."""
    return 1 if v >= hi_good else (-1 if v <= lo_bad else 0)


def expected():
    e = {}
    u10, u3 = load("us10y"), load("us3m")
    e["curve"] = 1 if (u10.iloc[-1] - u3.iloc[-1]) > 0 else -1

    stab = load("stablecoin_total_liquidity", col="total_cap_usd")
    g = stab.iloc[-1] / stab.iloc[-30] - 1
    e["stablecoin"] = 1 if g > 0.02 else (-1 if g < -0.02 else 0)

    e["dxy"] = -slope(load("dxy"))
    m2 = load("fred_us_m2", col="value")
    e["m2"] = 1 if (m2.iloc[-1] / m2.iloc[-13] - 1) > 0.04 else (-1 if (m2.iloc[-1] / m2.iloc[-13] - 1) < 0.01 else 0)

    fbs = load("fred_fed_balance_sheet", col="value")
    cut = fbs.index[-1] - pd.Timedelta(days=60)
    chg = fbs.iloc[-1] / fbs.loc[:cut].iloc[-1] - 1
    e["fed_bs"] = 1 if chg > 0.01 else (-1 if chg < -0.01 else 0)

    vix = load("vix").iloc[-1]
    e["vix"] = 1 if vix < 20 else (-1 if vix > 30 else 0)
    e["spx"] = slope(load("sp500"))
    hy = load("fred_hy_spread", col="value").iloc[-1]
    e["credit"] = 1 if hy < 3.5 else (-1 if hy > 5.5 else 0)
    e["btc_ma"] = slope(load("btcusd_daily_bitstamp", "ts"))
    f = int(load("fear_greed", col="value").iloc[-1])
    e["fng"] = 1 if f < 30 else (-1 if f > 70 else 0)
    e["hash"] = slope(load("bi_hash-rate", "ts", "value"), 60)
    ry = load("fred_real_yield10y", col="value").iloc[-1]
    e["real_yield"] = 1 if ry < 1.5 else (-1 if ry > 2.5 else 0)
    cpi = load("fred_cpi", col="value")
    cy = cpi.iloc[-1] / cpi.iloc[-13] - 1
    e["cpi"] = 1 if cy < 0.03 else (-1 if cy > 0.05 else 0)
    e["gold"] = slope(load("gold"))
    return e


def emitted():
    out = subprocess.run([PY, str(ROOT / "strategies" / "macro_regime_v3.py")],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print("engine failed to run:\n" + out.stdout[-800:] + out.stderr[-800:])
        raise SystemExit(2)
    got = {}
    for line in out.stdout.splitlines():
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) == 3 and parts[0] in expected_keys and parts[1].lstrip("+-").isdigit():
            got[parts[0]] = int(parts[1])
    return got, out.stdout


expected_keys = {"curve", "stablecoin", "dxy", "m2", "fed_bs", "vix", "spx", "credit",
                 "btc_ma", "fng", "hash", "real_yield", "cpi", "gold"}

exp = expected()
got, stdout = emitted()

print("=" * 62)
print("SIGNAL PARITY - engine output versus independent recomputation")
print("=" * 62)
print(f"  {'signal':12s} {'engine':>7s} {'checker':>8s}   status")
bad = []
for k in ("curve", "stablecoin", "dxy", "m2", "fed_bs", "vix", "spx", "credit",
          "btc_ma", "fng", "hash", "real_yield", "cpi", "gold"):
    a, b = got.get(k), exp.get(k)
    ok = a == b
    if not ok:
        bad.append(k)
    print(f"  {k:12s} {str(a):>7s} {str(b):>8s}   {'ok' if ok else 'MISMATCH'}")
print()
if bad:
    print(f"  PARITY: FAIL on {len(bad)} signal(s): {', '.join(bad)}")
    raise SystemExit(1)
print(f"  PARITY: PASS ({len(got)}/14 signals agree)")
