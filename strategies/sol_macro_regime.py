#!/usr/bin/env python3
"""
SOL MACRO REGIME ENGINE - multi-signal, phase-based allocation decision for Solana.
Uses macro_dataset/ to score the regime: HOLD SOL / CASH out / BUY the dip.

Structure is the ETH engine's (strategies/eth_macro_regime.py) so the two are
comparable signal for signal; the shared macro backbone is IDENTICAL, only group C
is asset-native. Weights that are new for SOL are marked EXPERIMENTAL and carry an
A/B in strategies/sol_macro_backtest.py - do not re-weight without one.

Signal groups (causal weights):
  A. LIQUIDITY (2.0): 10y-3m curve slope, stablecoin cap 30d change, DXY vs 200d MA,
     M2 YoY, Fed BS 60d change
  B. RISK APPETITE (1.5): VIX regime, SPX vs 200d MA, HY credit spread
  C. SOL INTERNALS: SOL vs 200d MA (2.0), SOL/BTC vs 200d MA (1.5, rotation gate),
     Solana TVL vs 60d MA (1.0), Solana stablecoin supply 30d change (1.0, EXPERIMENTAL),
     Solana DEX volume 7d vs 90d (0.5, EXPERIMENTAL), Fear & Greed contrarian (0.5)
  D. INFLATION / REAL (1.0): 10y real yield, CPI YoY, Gold vs 200d MA

Calendar rule (AGENTS.md integrity rule 3): every change/MA window is anchored in
DAYS, never in row counts - the Solana stablecoin chart is sparse before 2023 and
row offsets there are not 30-day horizons.

Output: full report to stdout (stateless - nothing saved).
"""
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
    df = df[~df.index.duplicated(keep="last")]
    if col in df.columns:
        return df[col]
    return df


def slope_score(s, n=200, prec=2):
    if s is None or len(s) < n:
        return 0, "insufficient data"
    ma = s.rolling(n).mean().iloc[-1]
    cur = s.iloc[-1]
    sc = 1 if cur > ma else (-1 if cur < ma else 0)
    return sc, f"{cur:,.{prec}f} {'above' if cur >= ma else 'below'} {n}d MA {ma:,.{prec}f}"


def change_score(s, days=30, pos_thr=0.02, neg_thr=-0.02, unit="%"):
    """Calendar-anchored change: compares the last value with the last value at
    least `days` CALENDAR days earlier (row offsets lie on sparse series)."""
    if s is None or len(s) < 2:
        return 0, "insufficient data"
    cut = s.index[-1] - pd.Timedelta(days=days)
    base = s.loc[:cut]
    if base.empty:
        return 0, "insufficient data"
    cur, prev = s.iloc[-1], base.iloc[-1]
    chg = (cur / prev - 1) if prev else 0
    sc = 1 if chg > pos_thr else (-1 if chg < neg_thr else 0)
    return sc, f"{days}d chg {chg*100:+.1f}{unit} (cur: {cur:,.0f})"


def solbtc_series():
    """SOL/BTC from aligned USD closes (crosses are computed, never fetched)."""
    sol = load("solusd_daily_yahoo", "ts")
    btc = load("btcusd_daily_bitstamp", "ts")
    if sol is None or btc is None:
        return None
    sol = sol[~sol.index.duplicated(keep="last")].sort_index()
    btc = btc[~btc.index.duplicated(keep="last")].sort_index()
    btc_d = btc.reindex(sol.index, method="ffill")
    return (sol / btc_d).dropna()


def main():
    signals, weights, reasons = {}, {}, {}

    # A. LIQUIDITY (2.0)
    u10, u3m = load("us10y"), load("us3m")
    if u10 is not None and u3m is not None:
        curve = u10 - u3m.reindex(u10.index).ffill()
        cur_c = curve.iloc[-1]
        sc = 1 if cur_c > 0 else -1
        signals["curve"], weights["curve"] = sc, 2.0
        reasons["curve"] = f"10y-3m spread {cur_c:.2f}% ({'steep normal' if cur_c > 0 else 'inverted'})"

    stab = load("stablecoin_total_liquidity", col="total_cap_usd")
    if stab is not None:
        sc, r = change_score(stab, 30, 0.02, -0.02)
        signals["stablecoin"], weights["stablecoin"] = sc, 2.0
        reasons["stablecoin"] = f"stablecoin cap {r}"

    dxy = load("dxy")
    if dxy is not None:
        sc, r = slope_score(dxy, 200)
        signals["dxy"] = -sc          # firm dollar is risk-off (sign fixed 2026-11-04)
        weights["dxy"] = 1.5
        reasons["dxy"] = f"DXY {r} ({'firm - headwind' if sc > 0 else 'soft - tailwind' if sc < 0 else 'at trend'})"

    m2 = load("fred_us_m2", col="value")
    if m2 is not None:
        cur_m2 = m2.iloc[-1]
        base_m2 = m2.loc[:m2.index[-1] - pd.Timedelta(days=365)]
        if len(base_m2) == 0:
            base_m2 = m2.iloc[:1]
        yoy = (cur_m2 / base_m2.iloc[-1] - 1) * 100
        sc = 1 if yoy > 4.0 else (-1 if yoy < 1.0 else 0)
        signals["m2"], weights["m2"] = sc, 2.0
        reasons["m2"] = f"M2 YoY {yoy:+.1f}% ({'expanding' if sc == 1 else ('contracting' if sc == -1 else 'neutral')})"

    fbs = load("fred_fed_balance_sheet", col="value")
    if fbs is not None:
        base = fbs.loc[:fbs.index[-1] - pd.Timedelta(days=60)]
        prev_fbs = base.iloc[-1] if len(base) else fbs.iloc[0]
        chg_fbs = (fbs.iloc[-1] / prev_fbs - 1) * 100
        sc = 1 if chg_fbs > 1.0 else (-1 if chg_fbs < -1.0 else 0)
        signals["fed_bs"], weights["fed_bs"] = sc, 1.5
        reasons["fed_bs"] = f"Fed balance sheet 60d chg {chg_fbs:+.1f}% ({'expanding' if sc == 1 else ('contracting' if sc == -1 else 'flat')})"

    # B. RISK APPETITE (1.5)
    vix = load("vix")
    if vix is not None:
        cur_vix = vix.iloc[-1]
        sc = 1 if cur_vix < 20 else (-1 if cur_vix > 30 else 0)
        signals["vix"], weights["vix"] = sc, 1.5
        reasons["vix"] = f"VIX {cur_vix:.1f} ({'calm risk-on' if sc == 1 else ('stress risk-off' if sc == -1 else 'neutral')})"

    spx = load("sp500")
    if spx is not None:
        sc, r = slope_score(spx, 200)
        signals["spx"], weights["spx"] = sc, 1.5
        reasons["spx"] = f"SPX {r}"

    hy = load("fred_hy_spread", col="value")
    if hy is not None:
        cur_hy = hy.iloc[-1]
        sc = 1 if cur_hy < 3.5 else (-1 if cur_hy > 5.5 else 0)
        signals["credit"], weights["credit"] = sc, 1.5
        reasons["credit"] = f"HY spread {cur_hy:.2f}% ({'tight risk-on' if sc == 1 else ('wide risk-off' if sc == -1 else 'neutral')})"

    # C. SOL INTERNALS
    sol = load("solusd_daily_yahoo", "ts")
    if sol is not None:
        sc, r = slope_score(sol, 200)
        signals["sol_ma"], weights["sol_ma"] = sc, 2.0
        reasons["sol_ma"] = f"SOL {r}"

    solbtc = solbtc_series()
    if solbtc is not None:
        sc, r = slope_score(solbtc, 200, prec=6)   # ratio, so two decimals round to zero
        signals["solbtc_ma"], weights["solbtc_ma"] = sc, 1.5
        reasons["solbtc_ma"] = f"SOL/BTC {r}"

    tvl = load("sol_tvl_defillama", col="tvl_usd")
    if tvl is not None:
        tvl_d = tvl.resample("D").ffill().dropna()
        base = tvl_d.loc[:tvl_d.index[-1] - pd.Timedelta(days=60)]
        if len(base):
            ma60 = base.tail(60).mean()
            cur_tvl = tvl_d.iloc[-1]
            sc = 1 if cur_tvl > ma60 else -1
            signals["sol_tvl"], weights["sol_tvl"] = sc, 1.0
            reasons["sol_tvl"] = (f"Solana TVL ${cur_tvl/1e9:,.2f}B "
                                  f"{'above' if sc > 0 else 'below'} 60d MA ${ma60/1e9:,.2f}B")

    # EXPERIMENTAL (A/B'd in sol_macro_backtest.py): stablecoin supply grown on Solana.
    sstab = load("sol_stablecoins_defillama", col="usd")
    if sstab is not None:
        recent = sstab.loc[sstab.index[-1] - pd.Timedelta(days=45):]
        if len(recent) >= 20:                      # density guard: sparse early years are skipped
            sc, r = change_score(sstab, 30, 0.02, -0.02)
            signals["sol_stable"], weights["sol_stable"] = sc, 1.0
            reasons["sol_stable"] = f"Solana stablecoin supply {r}"

    # EXPERIMENTAL: on-chain activity trend (DEX volume, 7d vs 90d median).
    dex = load("sol_dex_volume_defillama", col="usd")
    if dex is not None:
        dex = dex[dex.index >= dex.index[-1] - pd.Timedelta(days=120)]
        if len(dex) >= 60:
            v7, v90 = dex.tail(7).median(), dex.tail(90).median()
            if v90 > 0:
                ratio = v7 / v90
                sc = 1 if ratio > 1.25 else (-1 if ratio < 0.75 else 0)
                signals["sol_dex"], weights["sol_dex"] = sc, 0.5
                reasons["sol_dex"] = (f"Solana DEX volume 7d ${v7/1e6:,.0f}M vs 90d median "
                                      f"${v90/1e6:,.0f}M ({ratio:.2f}x)")

    fng = load("fear_greed", col="value")
    if fng is not None:
        cur_fng = float(fng.iloc[-1])
        sc = 1 if cur_fng < 30 else (-1 if cur_fng > 70 else 0)
        signals["fng"], weights["fng"] = sc, 0.5
        reasons["fng"] = f"F&G {cur_fng:.0f}"

    # D. INFLATION / REAL (1.0)
    ry = load("fred_real_yield10y", col="value")
    if ry is not None:
        cur_ry = ry.iloc[-1]
        sc = 1 if cur_ry < 1.5 else (-1 if cur_ry > 2.5 else 0)
        signals["real_yield"], weights["real_yield"] = sc, 1.0
        reasons["real_yield"] = f"10y real yield {cur_ry:.2f}% ({'supportive' if sc == 1 else ('restrictive' if sc == -1 else 'neutral')})"

    cpi = load("fred_cpi", col="value")
    if cpi is not None:
        base_cpi = cpi.loc[:cpi.index[-1] - pd.Timedelta(days=365)]
        if len(base_cpi) == 0:
            base_cpi = cpi.iloc[:1]
        yoy_cpi = (cpi.iloc[-1] / base_cpi.iloc[-1] - 1) * 100
        sc = 1 if yoy_cpi < 3.0 else (-1 if yoy_cpi > 5.0 else 0)
        signals["cpi"], weights["cpi"] = sc, 0.5
        reasons["cpi"] = f"CPI YoY {yoy_cpi:+.1f}% ({'contained' if sc == 1 else ('hot' if sc == -1 else 'neutral')})"

    gold = load("gold")
    if gold is not None:
        sc, r = slope_score(gold, 200)
        signals["gold"], weights["gold"] = sc, 0.5
        reasons["gold"] = f"gold {r}"

    total_w = sum(weights.values())
    score = round((sum(signals[k] * weights[k] for k in signals) / total_w) * 3, 1)

    if score >= 1.5:
        verdict, phase = "HOLD / ACCUMULATE", "PHASE 1: RISK-ON (hold + accumulate)"
        action = "Risk-ON. Hold SOL/ecosystem, deploy cash on drawdowns."
    elif score >= 0.5:
        verdict, phase = "HOLD", "PHASE 1: RISK-ON (hold)"
        action = "Macro supportive. Hold spot positions."
    elif score <= -1.5:
        verdict, phase = "LIQUIDATE TO CASH", "PHASE 2: RISK-OFF (cash)"
        action = "Severe macro headwinds. Move to cash/stablecoins."
    elif score <= -0.5:
        verdict, phase = "REDUCE", "PHASE 2: RISK-OFF (reduce)"
        action = "Risk-off regime. Trim exposure to cash."
    else:
        verdict, phase = "NEUTRAL / TRANSITION", "TRANSITION"
        action = "Mixed regime. Wait for directional clarity."

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print("=== SOL MACRO REGIME (Full Backbone + Solana Internals) ===\n")
    print(f"=== REGIME SCORE: {score:+.1f} -> {verdict} ===")
    for k in signals:
        print(f"  - {reasons.get(k, k)}")
    print(f"  ACTION: {action}\n")

    print(f"# SOL Macro Regime - {now}")
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
