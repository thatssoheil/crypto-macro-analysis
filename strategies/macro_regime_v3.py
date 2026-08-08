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
    # 3. DXY trend (weaker $ = risk-on)
    if dxy is not None:
        sc, r = slope_score(dxy)
        signals["dxy"] = sc
        weights["dxy"] = 1.5
        reasons.append(f"DXY {r}")
    # 4. M2 YoY growth (liquidity fuel - the macro backbone)
    if m2 is not None and len(m2) > 13:
        yoy = m2["value"].iloc[-1] / m2["value"].iloc[-13] - 1
        signals["m2"] = 1 if yoy > 0.04 else (-1 if yoy < 0.01 else 0)
        weights["m2"] = 2.0
        reasons.append(f"M2 YoY {yoy*100:+.1f}% ({'expanding' if yoy>0.04 else 'contracting' if yoy<0.01 else 'neutral'})")
    # 5. Fed balance sheet trend (QE = risk-on, QT = risk-off)
    if fed_bs is not None and len(fed_bs) > 60:
        chg = fed_bs["value"].iloc[-1] / fed_bs["value"].iloc[-61] - 1
        signals["fed_bs"] = 1 if chg > 0.01 else (-1 if chg < -0.01 else 0)
        weights["fed_bs"] = 1.5
        reasons.append(f"Fed balance sheet 60d chg {chg*100:+.1f}% ({'expanding (QE)' if chg>0.01 else 'contracting (QT)' if chg<-0.01 else 'flat'})")

    # ---- B. RISK APPETITE (weight 1.5) ----
    # 6. VIX regime (low vol = risk-on)
    if vix is not None:
        v = vix["close"].iloc[-1]
        signals["vix"] = 1 if v < 20 else (-1 if v > 30 else 0)
        weights["vix"] = 1.5
        reasons.append(f"VIX {v:.1f} ({'calm risk-on' if v<20 else 'stress risk-off' if v>30 else 'neutral'})")
    # 7. SPX trend
    if spx is not None:
        sc, _ = slope_score(spx)
        signals["spx"] = sc
        weights["spx"] = 1.5
        reasons.append(f"SPX {sc}")
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
        gold_sc, _ = slope_score(gold)
        signals["gold"] = gold_sc
        weights["gold"] = 0.5
        reasons.append(f"gold {gold_sc}")

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

    # Phase label for the phasic cash cycle
    if score >= 0.5: phase = "PHASE 1: RISK-ON (hold + accumulate)"
    elif score <= -0.5: phase = "PHASE 2: RISK-OFF (cash, wait)"
    else: phase = "TRANSITION (position for next leg)"

    # Stateless: print the full report to stdout, persist nothing.
    # Results are a pure function of the committed dataset - re-run to regenerate.
    print(f"# Macro Regime v3 - {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    print(f"## SCORE {score:+.1f} -> **{verdict}**")
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