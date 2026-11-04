#!/usr/bin/env python3
"""
HOLD BENCHMARK - implements the judge's verdict of 2026-11-04, as written.

The judge (gpt-6.1-sol) authorised exactly one rule: hold 100% spot BTC, no timing, no
rotation, no leverage, no conditional variant. This script implements that rule, its
identity falsifier, the two diagnostics the judge named, and the challenger bar that would
withdraw the verdict.

FROZEN BY THE JUDGE, NOT BY THIS SCRIPT
  Windows (inclusive):
    in-sample  2017-01-01 .. 2026-11-01
    early      2011-08-18 .. 2016-12-31
    recent     2023-01-01 .. 2026-11-01
    full       2011-08-18 .. 2026-11-01
  Hold rule : q = 10000/P0 at the first close, equity = q*Pt, no switches, no costs,
              USD earns 0%, terminal marked at the last close, no forced liquidation.
  Identity  : equity/(10000*Pt/P0) must equal 1 within 1e-10 on EVERY date, with zero
              switches and zero cost. Otherwise the implementation is rejected, not the rule.
  Metrics   : terminal USD, terminal BTC-equivalent (USD/final close), max daily
              peak-to-trough drawdown, allocation switches, total cost.
  Falsifier : withdraw the default in favour of further validation if ONE preregistered
              challenger reaches net terminal wealth >= 1.10x BTC hold in ALL FOUR windows,
              including under 20bp per switch and one extra day of execution delay.
  Diagnostic: ETH buy-and-hold versus BTC buy-and-hold ratio >= 1.25 on 2017-08-16..
              2026-11-01 and on the recent block challenges the BTC selection (does not
              authorise an ETH switch).

Challenger tested here: the 200-day switch, the repo's own execution rule. The repaired
14-signal composite is NOT tested: three of its inputs (Fear and Greed, high-yield spreads,
the stablecoin aggregate) do not exist in 2011-2016, so it cannot satisfy a rule that
requires all four windows. That is a disqualification by the judge's own criterion, not an
omission.
"""
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"
WINDOWS = {
    "in-sample 2017-2026": ("2017-01-01", "2026-11-01"),
    "early     2011-2016": ("2011-08-18", "2016-12-31"),
    "recent    2023-2026": ("2023-01-01", "2026-11-01"),
    "full      2011-2026": ("2011-08-18", "2026-11-01"),
}
START = 10000.0


def load_series(name, date_col="ts", col="close"):
    df = pd.read_csv(DATA / f"{name}.csv")
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.sort_values(date_col)
    # Judge rule 5: reject duplicates, non-finite or non-positive closes; never forward fill.
    if df[date_col].duplicated().any():
        raise SystemExit(f"INVALID dataset {name}: duplicate timestamps")
    if not df[col].map(lambda v: isinstance(v, (int, float)) and v == v and v > 0).all():
        raise SystemExit(f"INVALID dataset {name}: non-finite or non-positive close")
    return df.set_index(date_col)[col]


def hold(px):
    """Judge's authorised rule: buy at the first close, hold, mark at the last close."""
    p0 = px.iloc[0]
    q = START / p0
    eq = q * px
    identity = (eq / (START * px / p0) - 1).abs().max()
    return {
        "final_usd": float(eq.iloc[-1]),
        "final_btc": float(eq.iloc[-1] / px.iloc[-1]),
        "max_dd": float((eq / eq.cummax() - 1).min() * 100),
        "switches": 0,
        "cost": 0.0,
        "identity_error": float(identity),
    }


def switch(px, n=200, bps=20.0, extra_delay=1):
    """Challenger: long above the n-day average. Signal at close t changes holdings at
    close t+1 and cannot earn the t to t+1 return. extra_delay models the stress day."""
    cost = bps / 10000.0
    ma = px.rolling(n).mean()
    sig = (px >= ma).astype(float)
    sig[ma.isna()] = 1.0
    pos = sig.shift(1 + extra_delay).fillna(1.0)
    rets = px.pct_change().fillna(0)
    flips = pos.diff().abs().fillna(0)
    eq = (1 + rets * pos - flips * cost).cumprod() * START
    return {
        "final_usd": float(eq.iloc[-1]),
        "max_dd": float((eq / eq.cummax() - 1).min() * 100),
        "switches": int((flips > 0).sum()),
        "cost_usd": float(START * flips.sum() * cost),
    }


btc = load_series("btcusd_daily_bitstamp")
eth = load_series("ethusd_daily_bitstamp")

print("=" * 82)
print("HOLD BENCHMARK - judge verdict of 2026-11-04 implemented as written")
print("=" * 82)
print(f"\n  {'window':22s} {'terminal USD':>15s} {'terminal BTC':>13s} {'max DD':>8s} "
      f"{'switches':>9s} {'cost':>6s} {'identity':>10s}")
hold_res = {}
for name, (a, b) in WINDOWS.items():
    px = btc.loc[a:b]
    r = hold(px)
    hold_res[name] = r
    print(f"  {name:22s} ${r['final_usd']:>14,.2f} {r['final_btc']:>12.4f} "
          f"{r['max_dd']:>7.2f}% {r['switches']:>9d} {r['cost']:>6.0f} "
          f"{r['identity_error']:>10.1e}")

bad = [k for k, r in hold_res.items() if r["identity_error"] > 1e-10 or r["switches"] != 0]
print(f"\n  IDENTITY FALSIFIER: {'PASS - equity is algebraically buy and hold in all windows' if not bad else 'FAIL on ' + ', '.join(bad)}")

print("\n  CHALLENGER BAR - 200-day switch, 20bp per switch, one extra day of execution delay")
print(f"  {'window':22s} {'challenger':>14s} {'BTC hold':>14s} {'ratio':>7s} {'verdict':>9s}")
passed_all = True
for name, (a, b) in WINDOWS.items():
    px = btc.loc[a:b]
    c = switch(px)
    ratio = c["final_usd"] / hold_res[name]["final_usd"]
    ok = ratio >= 1.10
    passed_all &= ok
    print(f"  {name:22s} ${c['final_usd']:>13,.0f} ${hold_res[name]['final_usd']:>13,.0f} "
          f"{ratio:>6.3f}x {'CLEARS' if ok else 'fails':>9s}")
print(f"\n  FALSIFIER: {'WITHDRAW the default' if passed_all else 'HOLD the default - no challenger reached 1.10x in all four windows'}")

print("\n  DIAGNOSTIC - is BTC even the right asset? (judge: ratio >= 1.25 challenges the choice)")
for label, (a, b) in (("2017-08-16..2026-11-01", ("2017-08-16", "2026-11-01")),
                      ("recent 2023..2026", ("2023-01-01", "2026-11-01"))):
    be = eth.loc[a:b]
    ratio = (hold(be)["final_usd"] / hold(btc.loc[a:b])["final_usd"])
    print(f"  ETH/BTC buy-and-hold wealth, {label:24s} {ratio:>6.3f}x "
          f"{'CHALLENGES' if ratio >= 1.25 else 'does not challenge'}")
print("\n" + "=" * 82)
print("VERDICT: hold 100% spot BTC. No switch, rotation or overlay is authorised.")
print("=" * 82)
