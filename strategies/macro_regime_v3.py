#!/usr/bin/env python3
"""
MACRO REGIME ENGINE v3 - multi-signal, phase-based allocation decision.
Uses the full macro_dataset/ to score the regime: HOLD gems / CASH out / BUY the dip.

Signal groups (each contributes -2..+2, weights tuned to macro causality):
  A. LIQUIDITY (most causal for crypto): 10y-3m curve slope, stablecoin growth, DXY trend
  B. RISK APPETITE: VIX regime, SPX trend (200d), credit proxy
  C. CRYPTO INTERNAL: BTC vs 200d MA, F&G contrarian, on-chain health
  D. INFLATION/REAL ASSETS: gold trend (inflation hedge demand), commodity breadth

Output: full report to stdout (stateless - nothing persisted, re-run to regenerate).
No data fetch - consumes the local dataset only. Re-run anytime (cadence: weekly/mo).
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import numpy as np

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"

def load(name, date_col="date", val_cols=None):
    p = DATA / f"{name}.csv"
    if not p.exists(): return None
    df = pd.read_csv(p)
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    return df

def pct_ma(df, col, n=200):
    """% of series above its n-day MA: +1 if above, -1 if below, scaled by distance."""
    if df is None or len(df) < n: return 0.0, "insufficient data"
    ma = df[col].rolling(n).mean().iloc[-1]
    cur = df[col].iloc[-1]
    return (cur / ma - 1) * 100, f"{cur:.2f} vs MA{n} {ma:.2f}"

def trend_score(df, col="close", n=200):
    if df is None or len(df) < n: return 0, "insufficient data"
    above = df[col].iloc[-1] > df[col].rolling(n).mean().iloc[-1]
    return (1 if above else -1), f"{'above' if above else 'below'} {n}d MA"

def slope_score(df, col="close", n=200):
    """+1 if series above n-day MA, -1 below, 0 neutral. Returns (score, desc)."""
    if df is None or len(df) < n:
        return 0, "insufficient data"
    ma = df[col].rolling(n).mean().iloc[-1]
    cur = df[col].iloc[-1]
    if cur > ma: return 1, f"{cur:.2f} above {n}d MA {ma:.2f}"
    if cur < ma: return -1, f"{cur:.2f} below {n}d MA {ma:.2f}"
    return 0, f"{cur:.2f} at MA {ma:.2f}"


# Max tolerated age in days per input, by the cadence the source actually publishes on AND
# the cadence this dataset is actually refreshed at (on demand, weekly bot). A daily series
# legitimately sits 5-7 days old between Sunday refreshes, so the daily limit is 10, not 3:
# a gate that fires every Tuesday is a gate everyone learns to ignore.
FRESH_LIMITS = {
    "curve": 10, "stablecoin": 10, "dxy": 10, "m2": 75, "fed_bs": 14, "vix": 10,
    "spx": 10, "credit": 12, "btc_ma": 10, "fng": 10, "hash": 10, "real_yield": 12,
    "cpi": 75, "gold": 10,
}
# If any of these is stale the engine refuses to score at all: they are the backbone of
# the verdict, and stale values there silently invert a decision instead of degrading it.
CORE_INPUTS = ("btc_ma", "vix", "spx", "dxy", "curve")

def main():
    print("=== MACRO REGIME v4 (full FRED backbone) ===")
    btc = load("btcusd_daily_bitstamp", "ts")
    dxy = load("dxy")
    us10y, us3m = load("us10y"), load("us3m")
    vix, spx = load("vix"), load("sp500")
    gold, wti = load("gold"), load("wti")
    stab = load("stablecoin_total_liquidity")
    fng_df = load("fear_greed")
    hash_df = load("bi_hash-rate", "ts")
    m2 = load("fred_us_m2")
    fed_bs = load("fred_fed_balance_sheet")
    real_y = load("fred_real_yield10y")
    cpi = load("fred_cpi")
    hy = load("fred_hy_spread")

    signals = {}
    weights = {}
    reasons = []

    # ---- A. LIQUIDITY (weight 2.0) ----
    # 1. Yield curve 10y-3m (inversion = recession risk = risk-OFF)
    if us10y is not None and us3m is not None:
        spread = us10y["close"].iloc[-1] - us3m["close"].iloc[-1]
        signals["curve"] = 1 if spread > 0 else -1
        weights["curve"] = 2.0
        reasons.append(f"10y-3m spread {spread:.2f}% ({'steep normal' if spread>0 else 'INVERTED risk-off'})")
    # 2. Stablecoin growth (liquidity into crypto)
    if stab is not None and len(stab) > 30:
        g = stab["total_cap_usd"].iloc[-1] / stab["total_cap_usd"].iloc[-30] - 1
        signals["stablecoin"] = 1 if g > 0.02 else (-1 if g < -0.02 else 0)
        weights["stablecoin"] = 2.0
        reasons.append(f"stablecoin cap 30d chg {g*100:+.1f}% ({'liquidity in' if g>0.02 else 'draining' if g<-0.02 else 'flat'})")
    # 3. DXY trend (a FIRM dollar is risk-off: forward BTC returns are 4.3% over 60 days
    # with the dollar above its 200d MA versus 22.0% with it below, 2017-2026. The signal
    # therefore takes the NEGATIVE of the above/below score. Fixed 2026-11-04: this vote
    # used to read +1 for a firm dollar, which contradicted its own stated intent.)
    if dxy is not None:
        sc, r = slope_score(dxy)
        signals["dxy"] = -sc
        weights["dxy"] = 1.5
        reasons.append(f"DXY {r} ({'firm - headwind' if sc > 0 else 'soft - tailwind' if sc < 0 else 'at trend'})")
    # 4. M2 YoY growth (liquidity fuel - the macro backbone)
    if m2 is not None and len(m2) > 13:
        yoy = m2["value"].iloc[-1] / m2["value"].iloc[-13] - 1
        signals["m2"] = 1 if yoy > 0.04 else (-1 if yoy < 0.01 else 0)
        weights["m2"] = 2.0
        reasons.append(f"M2 YoY {yoy*100:+.1f}% ({'expanding' if yoy>0.04 else 'contracting' if yoy<0.01 else 'neutral'})")
    # 5. Fed balance sheet trend (QE = risk-on, QT = risk-off)
    # Fixed 2026-11-04: WALCL is a WEEKLY series, so iloc[-61] was a 420-day change printed
    # as "60d". Now measured on the calendar: the last observation at or before 60 days ago.
    if fed_bs is not None and len(fed_bs) > 12:
        cut = fed_bs.index[-1] - pd.Timedelta(days=60)
        base = fed_bs.loc[:cut, "value"]
        if len(base) == 0:
            signals["fed_bs"] = 0; weights["fed_bs"] = 1.5
            reasons.append("Fed balance sheet 60d chg n/a (insufficient history)")
        else:
            chg = fed_bs["value"].iloc[-1] / base.iloc[-1] - 1
            signals["fed_bs"] = 1 if chg > 0.01 else (-1 if chg < -0.01 else 0)
            weights["fed_bs"] = 1.5
            reasons.append(f"Fed balance sheet 60d chg {chg*100:+.1f}% ({'expanding' if chg>0.01 else 'contracting' if chg<-0.01 else 'flat'})")

    # ---- B. RISK APPETITE (weight 1.5) ----
    # 6. VIX regime (low vol = risk-on)
    if vix is not None:
        v = vix["close"].iloc[-1]
        signals["vix"] = 1 if v < 20 else (-1 if v > 30 else 0)
        weights["vix"] = 1.5
        reasons.append(f"VIX {v:.1f} ({'calm risk-on' if v<20 else 'stress risk-off' if v>30 else 'neutral'})")
    # 7. SPX trend
    if spx is not None:
        sc, r = slope_score(spx)
        signals["spx"] = sc
        weights["spx"] = 1.5
        reasons.append(f"SPX {r}")
    # 8. Credit spreads (HY = risk appetite canary)
    if hy is not None and len(hy) > 5:
        hyv = hy["value"].iloc[-1]
        signals["credit"] = 1 if hyv < 3.5 else (-1 if hyv > 5.5 else 0)
        weights["credit"] = 1.5
        reasons.append(f"HY spread {hyv:.2f}% ({'tight risk-on' if hyv<3.5 else 'wide risk-off' if hyv>5.5 else 'neutral'})")

    # ---- C. CRYPTO INTERNAL (weight 2.0) ----
    # 9. BTC vs 200d MA (the validated primary)
    if btc is not None:
        sc, r = slope_score(btc, "close")
        signals["btc_ma"] = sc
        weights["btc_ma"] = 2.0
        reasons.append(f"BTC {r}")
    # 10. F&G contrarian (extreme only)
    if fng_df is not None:
        f = int(fng_df["value"].iloc[-1])
        signals["fng"] = 1 if f < 30 else (-1 if f > 70 else 0)
        weights["fng"] = 1.0
        reasons.append(f"F&G {f}")
    # 11. Onchain health (hash rate trend)
    if hash_df is not None:
        hd = hash_df.rename(columns={"value": "close"})
        sc, r = slope_score(hd, "close", n=60)
        signals["hash"] = sc
        weights["hash"] = 0.5
        reasons.append(f"hashrate {r}")

    # ---- D. INFLATION/REAL (weight 1.0) ----
    # 12. Real yield (rising real yield = headwind for gold/BTC)
    if real_y is not None and len(real_y) > 5:
        ry = real_y["value"].iloc[-1]
        signals["real_yield"] = 1 if ry < 1.5 else (-1 if ry > 2.5 else 0)
        weights["real_yield"] = 1.0
        reasons.append(f"10y real yield {ry:.2f}% ({'low supportive' if ry<1.5 else 'high headwind' if ry>2.5 else 'neutral'})")
    # 13. CPI momentum (inflation trend)
    if cpi is not None and len(cpi) > 13:
        cpi_yoy = cpi["value"].iloc[-1] / cpi["value"].iloc[-13] - 1
        signals["cpi"] = 1 if cpi_yoy < 0.03 else (-1 if cpi_yoy > 0.05 else 0)
        weights["cpi"] = 0.5
        reasons.append(f"CPI YoY {cpi_yoy*100:+.1f}% ({'contained' if cpi_yoy<0.03 else 'hot' if cpi_yoy>0.05 else 'neutral'})")
    # 14. Gold trend
    if gold is not None:
        gold_sc, r = slope_score(gold)
        signals["gold"] = gold_sc
        weights["gold"] = 0.5
        reasons.append(f"gold {r}")

    # ---- INPUT HEALTH (freshness gate, added 2026-11-04) ----
    # Every loader only tests existence. A series that stops updating therefore reads as
    # valid forever, and the audit cannot see it because it measures gaps BETWEEN rows.
    # This block makes age visible and makes a stale CORE input a hard stop.
    frames = {"curve": us10y, "stablecoin": stab, "dxy": dxy, "m2": m2, "fed_bs": fed_bs,
              "vix": vix, "spx": spx, "credit": hy, "btc_ma": btc, "fng": fng_df,
              "hash": hash_df, "real_yield": real_y, "cpi": cpi, "gold": gold}
    now_utc = pd.Timestamp.now(tz="UTC")
    health, stale_core = [], []
    for key, frame in frames.items():
        if frame is None or len(frame) == 0:
            health.append((key, "-", "-", "MISSING"))
            if key in CORE_INPUTS: stale_core.append(key)
            continue
        last = frame.index[-1]
        age = int((now_utc - last).days)
        status = "OK" if age <= FRESH_LIMITS.get(key, 7) else "STALE"
        health.append((key, last.strftime("%Y-%m-%d"), str(age), status))
        if status == "STALE" and key in CORE_INPUTS:
            stale_core.append(key)

    print("\n=== INPUT HEALTH (as of %s) ===" % now_utc.strftime("%Y-%m-%d %H:%M UTC"))
    for key, d, age, status in health:
        print(f"  {key:12s} {d:12s} {age:>4s}d  {status}")
    missing = [k for k, _, _, s in health if s == "MISSING"]
    if stale_core or len(signals) < 14:
        print(f"\nREFUSING TO SCORE: stale/missing core input -> {', '.join(stale_core) or 'none'}"
              f" | signals {len(signals)}/14 | missing {', '.join(missing) or 'none'}")
        print("A stale core input does not degrade this verdict, it inverts it. Fix the source,")
        print("or re-run with --allow-stale-core to see the degraded read explicitly.")
        if "--allow-stale-core" not in sys.argv:
            raise SystemExit(2)

    # ---- Aggregate ----
    total_w = sum(weights.values())
    score = sum(signals[k] * weights[k] for k in signals) / total_w * 3  # normalize to -3..+3
    score = round(score, 1)

    if score >= 1.5: verdict, action = "HOLD / ACCUMULATE", "Risk-ON. Hold gems, deploy cash on drawdowns (buy the dip)."
    elif score >= 0.5: verdict, action = "HOLD", "Mildly risk-on. Hold existing positions, no aggressive buys."
    elif score <= -1.5: verdict, action = "LIQUIDATE TO CASH", "Risk-OFF. Reduce/exit to cash, wait for the next leg."
    elif score <= -0.5: verdict, action = "REDUCE / CASH", "Mixed risk-off. Trim to cash, wait for clearer regime."
    else: verdict, action = "NEUTRAL", "Mixed signals. Hold or reduce, await clarity."

    print(f"\n=== REGIME SCORE: {score:+.1f} -> {verdict} ===")
    for r in reasons: print(f"  - {r}")
    print(f"  ACTION: {action}")

    # Phase label for the phasic cash cycle. The instruction is banded, not fixed: at a
    # score of +0.5 to +1.4 the engine is holding, NOT deploying. Fixed 2026-11-04: this
    # label used to read "hold + accumulate" for every PHASE 1 day, including days when the
    # verdict two lines above said "no aggressive buys".
    if score >= 0.5:
        phase = ("PHASE 1: RISK-ON (hold + accumulate)" if score >= 1.5
                 else "PHASE 1: RISK-ON (hold only, no new deployment)")
    elif score <= -0.5: phase = "PHASE 2: RISK-OFF (cash, wait)"
    else: phase = "TRANSITION (position for next leg)"

    # Stateless: print the full report to stdout, persist nothing.
    # Results are a pure function of the committed dataset - re-run to regenerate.
    print(f"# Macro Regime v3 - {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    print(f"## SCORE {score:+.1f} -> **{verdict}**")
    print(f"**Coverage:** {len(signals)}/14 signals, weight {sum(weights.values()):.1f}/19.0")
    print(f"**Phase:** {phase}")
    print(f"**Action:** {action}")
    print("| Signal | Value | Weight |")
    print("|---|---|---|")
    for k in signals:
        print(f"| {k} | {signals[k]:+d} | {weights[k]} |")
    print("| Reason |")
    print("|---|")
    for r in reasons: print(f"| {r} |")
    print(f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_")
    print(f"\nPHASE: {phase}")

if __name__ == "__main__":
    main()