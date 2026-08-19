#!/usr/bin/env python3
"""
ETH MACRO REGIME ENGINE - multi-signal, phase-based allocation decision for Ethereum.
Uses macro_dataset/ to score the regime: HOLD ETH / CASH out / BUY the dip.

Signal groups (causal weights):
  A. LIQUIDITY (2.0): 10y-3m curve slope, stablecoin cap 30d change, DXY vs 200d MA, M2 YoY, Fed BS 60d change
  B. RISK APPETITE (1.5): VIX regime, SPX vs 200d MA, HY credit spread
  C. ETH INTERNALS (2.0): ETH vs 200d MA, ETH/BTC vs 200d MA, ETH TVL vs 60d MA, Fear & Greed contrarian
  D. INFLATION / REAL (1.0): 10y real yield, CPI YoY, Gold vs 200d MA

Output: full report to stdout (stateless - nothing saved).
"""
import csv
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import numpy as np

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"


def load(name, date_col="date", col="close"):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    if col in df.columns:
        return df[col]
    return df


def slope_score(s, n=200):
    if s is None or len(s) < n:
        return 0, "insufficient data"
    ma = s.rolling(n).mean().iloc[-1]
    cur = s.iloc[-1]
    sc = 1 if cur > ma else (-1 if cur < ma else 0)
    return sc, f"{cur:.2f} {'above' if cur >= ma else 'below'} {n}d MA {ma:.2f}"


def change_score(s, periods=30, pos_thr=0.02, neg_thr=-0.02, unit="%"):
    if s is None or len(s) < periods + 1:
        return 0, "insufficient data"
    cur = s.iloc[-1]
    prev = s.iloc[-1 - periods]
    chg = (cur / prev - 1) if prev != 0 else 0
    sc = 1 if chg > pos_thr else (-1 if chg < neg_thr else 0)
    return sc, f"{periods}d chg {chg*100:+.1f}{unit} (cur: {cur:,.0f})"


def bound_score(s, low, high, invert=False):
    if s is None or len(s) == 0:
        return 0, "insufficient data"
    cur = float(s.iloc[-1])
    if invert:
        sc = 1 if cur < low else (-1 if cur > high else 0)
    else:
        sc = -1 if cur < low else (1 if cur > high else 0)
    return sc, f"{cur:.2f}"


def main():
    signals = {}
    weights = {}
    reasons = {}

    # A. LIQUIDITY (2.0)
    u10 = load("us10y")
    u3m = load("us3m")
    if u10 is not None and u3m is not None:
        curve = u10 - u3m.reindex(u10.index).ffill()
        cur_c = curve.iloc[-1]
        sc = 1 if cur_c > 0 else -1
        signals["curve"] = sc
        weights["curve"] = 2.0
        reasons["curve"] = f"10y-3m spread {cur_c:.2f}% ({'steep normal' if cur_c > 0 else 'inverted'})"

    stab = load("stablecoin_total_liquidity", col="total_cap_usd")
    if stab is not None:
        sc, r = change_score(stab, 30, 0.02, -0.02)
        signals["stablecoin"] = sc
        weights["stablecoin"] = 2.0
        reasons["stablecoin"] = f"stablecoin cap {r}"

    dxy = load("dxy")
    if dxy is not None:
        sc, r = slope_score(dxy, 200)
        signals["dxy"] = sc
        weights["dxy"] = 1.5
        reasons["dxy"] = f"DXY {r}"

    m2 = load("fred_us_m2", col="value")
    if m2 is not None:
        cur_m2 = m2.iloc[-1]
        prev_m2 = m2.iloc[-13] if len(m2) > 13 else m2.iloc[0]
        yoy = (cur_m2 / prev_m2 - 1) * 100
        sc = 1 if yoy > 4.0 else (-1 if yoy < 1.0 else 0)
        signals["m2"] = sc
        weights["m2"] = 2.0
        reasons["m2"] = f"M2 YoY {yoy:+.1f}% ({'expanding' if sc == 1 else ('contracting' if sc == -1 else 'neutral')})"

    fbs = load("fred_fed_balance_sheet", col="value")
    if fbs is not None:
        cur_fbs = fbs.iloc[-1]
        prev_fbs = fbs.iloc[-61] if len(fbs) > 61 else fbs.iloc[0]
        chg_fbs = (cur_fbs / prev_fbs - 1) * 100
        sc = 1 if chg_fbs > 1.0 else (-1 if chg_fbs < -1.0 else 0)
        signals["fed_bs"] = sc
        weights["fed_bs"] = 1.5
        reasons["fed_bs"] = f"Fed balance sheet 60d chg {chg_fbs:+.1f}% ({'expanding (QE)' if sc == 1 else ('contracting (QT)' if sc == -1 else 'neutral')})"

    # B. RISK APPETITE (1.5)
    vix = load("vix")
    if vix is not None:
        cur_vix = vix.iloc[-1]
        sc = 1 if cur_vix < 20 else (-1 if cur_vix > 30 else 0)
        signals["vix"] = sc
        weights["vix"] = 1.5
        reasons["vix"] = f"VIX {cur_vix:.1f} ({'calm risk-on' if sc == 1 else ('stress risk-off' if sc == -1 else 'neutral')})"

    spx = load("sp500")
    if spx is not None:
        sc, r = slope_score(spx, 200)
        signals["spx"] = sc
        weights["spx"] = 1.5
        reasons["spx"] = f"SPX {r}"

    hy = load("fred_hy_spread", col="value")
    if hy is not None:
        cur_hy = hy.iloc[-1]
        sc = 1 if cur_hy < 3.5 else (-1 if cur_hy > 5.5 else 0)
        signals["credit"] = sc
        weights["credit"] = 1.5
        reasons["credit"] = f"HY spread {cur_hy:.2f}% ({'tight risk-on' if sc == 1 else ('wide risk-off' if sc == -1 else 'neutral')})"

    # C. ETH INTERNALS (2.0)
    eth = load("ethusd_daily_bitstamp", "ts")
    if eth is not None:
        sc, r = slope_score(eth, 200)
        signals["eth_ma"] = sc
        weights["eth_ma"] = 2.0
        reasons["eth_ma"] = f"ETH {r}"

    ethbtc = load("ethbtc_daily_bitstamp", "ts")
    if ethbtc is not None:
        sc, r = slope_score(ethbtc, 200)
        signals["ethbtc_ma"] = sc
        weights["ethbtc_ma"] = 1.5
        reasons["ethbtc_ma"] = f"ETH/BTC {r}"

    eth_tvl = load("eth_tvl_defillama", col="tvl_usd")
    if eth_tvl is not None:
        sc, r = slope_score(eth_tvl, 60)
        signals["eth_tvl"] = sc
        weights["eth_tvl"] = 1.0
        reasons["eth_tvl"] = f"ETH TVL {r}"

    fng = load("fear_greed", col="value")
    if fng is not None:
        cur_fng = float(fng.iloc[-1])
        sc = 1 if cur_fng < 30 else (-1 if cur_fng > 70 else 0)
        signals["fng"] = sc
        weights["fng"] = 0.5
        reasons["fng"] = f"F&G {cur_fng:.0f}"

    # D. INFLATION / REAL (1.0)
    ry = load("fred_real_yield10y", col="value")
    if ry is not None:
        cur_ry = ry.iloc[-1]
        sc = 1 if cur_ry < 1.5 else (-1 if cur_ry > 2.5 else 0)
        signals["real_yield"] = sc
        weights["real_yield"] = 1.0
        reasons["real_yield"] = f"10y real yield {cur_ry:.2f}% ({'supportive' if sc == 1 else ('restrictive' if sc == -1 else 'neutral')})"

    cpi = load("fred_cpi", col="value")
    if cpi is not None:
        cur_cpi = cpi.iloc[-1]
        prev_cpi = cpi.iloc[-13] if len(cpi) > 13 else cpi.iloc[0]
        yoy_cpi = (cur_cpi / prev_cpi - 1) * 100
        sc = 1 if yoy_cpi < 3.0 else (-1 if yoy_cpi > 5.0 else 0)
        signals["cpi"] = sc
        weights["cpi"] = 0.5
        reasons["cpi"] = f"CPI YoY {yoy_cpi:+.1f}% ({'contained' if sc == 1 else ('hot' if sc == -1 else 'neutral')})"

    gold = load("gold")
    if gold is not None:
        sc, r = slope_score(gold, 200)
        signals["gold"] = sc
        weights["gold"] = 0.5
        reasons["gold"] = f"gold {r}"

    total_w = sum(weights.values())
    w_sum = sum(signals[k] * weights[k] for k in signals)
    score = round((w_sum / total_w) * 3, 1)

    if score >= 1.5:
        verdict = "HOLD / ACCUMULATE"
        phase = "PHASE 1: RISK-ON (hold + accumulate)"
        action = "Risk-ON. Hold ETH/ecosystem, deploy cash on drawdowns."
    elif score >= 0.5:
        verdict = "HOLD"
        phase = "PHASE 1: RISK-ON (hold)"
        action = "Macro supportive. Hold spot positions."
    elif score <= -1.5:
        verdict = "LIQUIDATE TO CASH"
        phase = "PHASE 2: RISK-OFF (cash)"
        action = "Severe macro headwinds. Move to cash/stablecoins."
    elif score <= -0.5:
        verdict = "REDUCE"
        phase = "PHASE 2: RISK-OFF (reduce)"
        action = "Risk-off regime. Trim exposure to cash."
    else:
        verdict = "NEUTRAL / TRANSITION"
        phase = "TRANSITION"
        action = "Mixed regime. Wait for directional clarity."

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"=== ETH MACRO REGIME (Full Backbone + ETH Internals) ===\n")
    print(f"=== REGIME SCORE: {score:+.1f} -> {verdict} ===")
    for k in signals:
        print(f"  - {reasons.get(k, k)}")
    print(f"  ACTION: {action}\n")

    print(f"# ETH Macro Regime - {now}")
    print(f"## SCORE {score:+.1f} -> **{verdict}**")
    print(f"**Phase:** {phase}")
    print(f"**Action:** {action}")
    print("\n| Signal | Value | Weight |")
    print("|---|---|---|")
    for k in signals:
        print(f"| {k} | {signals[k]:+d} | {weights[k]:.1f} |")
    print("\n| Reason |")
    print("|---|")
    for k in signals:
        print(f"| {reasons.get(k, '')} |")


if __name__ == "__main__":
    main()
