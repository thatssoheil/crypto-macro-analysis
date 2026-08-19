#!/usr/bin/env python3
"""
ETH MACRO REGIME BACKTEST (2017-2026).
Pointwise backtest of the ETH Macro Regime models vs 200d MA filter and Buy & Hold.

Strategies evaluated:
  1. Buy & Hold ETH
  2. ETH 200-day MA Trend Filter (no-lookahead, t-1 close applied to day t)
  3. ETH 200d MA + ETH/BTC 200d MA Dual Trend Filter
  4. ETH 50d MA OR DD-20% Breaker
  5. ETH Macro Multi-Signal Composite (Macro + ETH TVL + ETH/BTC)

Conventions:
  - Daily closes only, $10k start, cash 0% yield.
  - Position for day t is decided by signals at day t-1 (.shift(1), no lookahead).
  - Stateless: prints results to stdout, nothing persisted.
"""
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "macro_dataset"

W, END = "2017-08-16", "2026-08-08"


def load(name, date_col="date", col="close"):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    return df[col]


def slope(s, n=200):
    """+1 above n-MA, -1 below, 0 equal."""
    ma = s.rolling(n).mean()
    return np.sign(s - ma)


def bands(s, lo, hi, lo_v, hi_v):
    out = pd.Series(0.0, index=s.index)
    out[s < lo_v] = 1.0
    out[s > hi_v] = -1.0
    return out


def main():
    eth = load("ethusd_daily_bitstamp", "ts").loc[W:END]
    idx = eth.index

    # Signals
    sig = {}

    # A. LIQUIDITY (2.0)
    u10 = load("us10y"); u3m = load("us3m")
    curve = (u10 - u3m.reindex(u10.index).ffill()).dropna()
    sig["curve"] = (np.where(curve > 0, 1.0, -1.0), 2.0)

    stab = load("stablecoin_total_liquidity", col="total_cap_usd")
    if stab is not None:
        g = stab / stab.shift(30) - 1
        sig["stablecoin"] = (bands(g, None, None, 0.02, -0.02), 2.0)

    sig["dxy"] = (slope(load("dxy")), 1.5)

    m2 = load("fred_us_m2", col="value")
    if m2 is not None:
        yoy = m2 / m2.shift(12) - 1
        sig["m2"] = (bands(yoy, None, None, 0.04, 0.01), 2.0)

    fbs = load("fred_fed_balance_sheet", col="value")
    if fbs is not None:
        chg = fbs / fbs.shift(60) - 1
        sig["fed_bs"] = (bands(chg, None, None, 0.01, -0.01), 1.5)

    # B. RISK APPETITE (1.5)
    sig["vix"] = (bands(load("vix"), None, None, 20.0, 30.0), 1.5)
    sig["spx"] = (slope(load("sp500")), 1.5)
    hy = load("fred_hy_spread", col="value")
    if hy is not None:
        sig["credit"] = (bands(hy, None, None, 3.5, 5.5), 1.5)

    # C. ETH INTERNALS (2.0)
    sig["eth_ma"] = (slope(eth), 2.0)

    ethbtc = load("ethbtc_daily_bitstamp", "ts")
    if ethbtc is not None:
        sig["ethbtc_ma"] = (slope(ethbtc.reindex(idx).ffill()), 1.5)

    eth_tvl = load("eth_tvl_defillama", col="tvl_usd")
    if eth_tvl is not None:
        sig["eth_tvl"] = (slope(eth_tvl.reindex(idx).ffill(), 60), 1.0)

    fng = load("fear_greed", col="value")
    if fng is not None:
        sig["fng"] = (bands(fng, None, None, 30.0, 70.0), 0.5)

    # D. INFLATION / REAL (1.0)
    ry = load("fred_real_yield10y", col="value")
    if ry is not None:
        sig["real_yield"] = (bands(ry, None, None, 1.5, 2.5), 1.0)
    cpi = load("fred_cpi", col="value")
    if cpi is not None:
        cy = cpi / cpi.shift(12) - 1
        sig["cpi"] = (bands(cy, None, None, 0.03, 0.05), 0.5)
    sig["gold"] = (slope(load("gold")), 0.5)

    # Build multi-signal composite score
    WTS = {k: v for k, (_, v) in sig.items()}
    avail = {}
    for k, (s, w) in sig.items():
        if isinstance(s, np.ndarray):
            s = pd.Series(s, index=curve.index)
        avail[k] = s.reindex(idx).ffill()

    sig_df = pd.DataFrame(avail)
    wsum = (sig_df.notna() * pd.Series(WTS)).sum(axis=1)
    score = (sig_df.fillna(0) * pd.Series(WTS)).sum(axis=1) / wsum * 3

    # Simulation engine
    def simulate(in_market_series, name):
        in_market = in_market_series.shift(1).fillna(1.0)  # t-1 decision for return t
        rets = eth.pct_change().fillna(0)
        eq = (1 + rets * in_market).cumprod() * 10000
        dd = (eq / eq.cummax() - 1).min() * 100
        years = len(eq) / 365.25
        cagr = ((eq.iloc[-1] / 10000) ** (1 / years) - 1) * 100
        return {
            "name": name,
            "final": float(eq.iloc[-1]),
            "pct": float((eq.iloc[-1] / 10000 - 1) * 100),
            "cagr": float(cagr),
            "max_dd": float(dd),
            "cash_days": int((in_market == 0).sum()),
            "flips": int((in_market.diff().abs() > 0).sum()),
        }, eq

    # Define strategies
    # 1. 200d MA filter
    ma200 = eth.rolling(200).mean()
    strat_ma200 = (eth >= ma200).astype(float)

    # 2. 50d MA filter
    ma50 = eth.rolling(50).mean()
    strat_ma50 = (eth >= ma50).astype(float)

    # 3. 50d MA OR DD-20% breaker
    peak = eth.cummax()
    dd_pct = (eth / peak - 1) * 100
    strat_breaker = ((eth >= ma50) & (dd_pct >= -20)).astype(float)

    # 4. ETH 200d MA + ETH/BTC 200d MA Dual Filter
    if ethbtc is not None:
        ethbtc_s = ethbtc.reindex(idx).ffill()
        ma_ethbtc = ethbtc_s.rolling(200).mean()
        strat_dual = ((eth >= ma200) & (ethbtc_s >= ma_ethbtc)).astype(float)
    else:
        strat_dual = strat_ma200

    # 5. Multi-signal composite (score >= +0.5)
    strat_comp_05 = (score >= 0.5).astype(float)

    # 6. Composite with Hysteresis (entry +0.5, exit -0.5, 5d)
    raw = pd.Series(0.0, index=idx)
    raw[score >= 0.5] = 1.0
    raw[score <= -0.5] = 0.0
    strat_comp_hyst = (raw.rolling(5).mean() >= 0.5).astype(float)

    runs = [
        ("ETH Buy & Hold", pd.Series(1.0, index=idx)),
        ("ETH 200d MA Filter", strat_ma200),
        ("ETH 50d MA Filter", strat_ma50),
        ("ETH 50d MA + DD-20% Breaker", strat_breaker),
        ("ETH Dual Filter (ETH + ETH/BTC)", strat_dual),
        ("ETH Macro Composite (>= +0.5)", strat_comp_05),
        ("ETH Macro Hysteresis (5d)", strat_comp_hyst),
    ]

    results, eqs = [], {}
    for name, s_in in runs:
        r, eq = simulate(s_in, name)
        results.append(r)
        eqs[name] = eq

    print(f"=== ETH MACRO REGIME BACKTEST {W} -> {END} ($10k) ===\n")
    print(f"{'Strategy':32} {'Final ($)':>14} {'Return %':>12} {'CAGR %':>10} {'Max DD %':>10} {'Cash Days':>10} {'Flips':>8}")
    print("-" * 102)
    for r in results:
        print(f"{r['name']:32} ${r['final']:>13,.0f} {r['pct']:>+11,.1f}% {r['cagr']:>+9.1f}% {r['max_dd']:>9.1f}% {r['cash_days']:>10} {r['flips']:>8}")

    # Yearly returns
    print("\nYearly returns %:")
    tracked = ["ETH Buy & Hold", "ETH 200d MA Filter", "ETH 50d MA + DD-20% Breaker", "ETH Macro Composite (>= +0.5)"]
    yearly = {}
    for label in tracked:
        y = eqs[label].resample("YE").last().pct_change()
        y.iloc[0] = eqs[label].resample("YE").last().iloc[0] / 10000 - 1
        yearly[label] = {str(d.date())[:4]: round(float(v) * 100, 1) for d, v in y.items()}

    yrs = sorted({y for d in yearly.values() for y in d})
    print(f"{'Year':6} {'B&H':>10} {'200d MA':>10} {'50d+DD20%':>12} {'Macro Comp':>12}")
    print("-" * 54)
    for y in yrs:
        print(f"{y:6} {yearly['ETH Buy & Hold'].get(y, float('nan')):>10.1f} {yearly['ETH 200d MA Filter'].get(y, float('nan')):>10.1f} {yearly['ETH 50d MA + DD-20% Breaker'].get(y, float('nan')):>12.1f} {yearly['ETH Macro Composite (>= +0.5)'].get(y, float('nan')):>12.1f}")


if __name__ == "__main__":
    main()
