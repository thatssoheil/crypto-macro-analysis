#!/usr/bin/env python3
"""
MACRO REGIME v4 COMPOSITE BACKTEST (2017-2026).
Pointwise replay of the v4 engine's 14 signals from the LOCAL dataset, no lookahead.
Question: does the multi-signal macro composite beat the 200d-MA filter alone, and buy-hold?

Method:
  - Every signal computed on its own native calendar (monthly M2/CPI shift(12),
    weekly Fed-BS shift(60) -> matches engine's iloc[-n] semantics), then
    reindexed to BTC trading days and forward-filled (ffill = last known value).
  - Series not yet started (stablecoin 2017-11, F&G 2018-05, HY 2023-08) are NaN
    -> excluded from the weighted mean, exactly like the engine's "available signals" rule.
  - Score = sum(sig*w)/sum(available w)*3  (engine normalization).
  - NO LOOKAHEAD: position for day t is decided by score at day t-1 (close-based signals
    applied to the NEXT day's return). Same convention applied to the MA-200 baseline.
  - In-market iff score >= +0.5 (engine's PHASE 1 boundary). Sensitivity shown for 0.0/-0.5.
  - Cash earns 0%. Daily closes only. $10k start.
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "macro_dataset"
OUT = ROOT / "data" / "macro"
W, END = "2017-01-01", "2026-08-03"


def load(name, date_col="date", col="close"):
    df = pd.read_csv(DATA / f"{name}.csv")
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    return df[col]


def slope(s, n=200):
    """+1 above n-MA, -1 below, 0 equal (engine slope_score)."""
    ma = s.rolling(n).mean()
    return np.sign(s - ma)


def bands(s, lo, hi, lo_v, hi_v):
    """Threshold signal on a change series: +1 below lo_v, -1 above hi_v, else 0."""
    out = pd.Series(0.0, index=s.index)
    out[s < lo_v] = 1.0
    out[s > hi_v] = -1.0
    return out


def main():
    btc = load("btcusd_daily_bitstamp", "ts").loc[W:END]
    idx = btc.index

    sig = {}

    # A. LIQUIDITY
    u10 = load("us10y"); u3m = load("us3m")
    curve = (u10 - u3m.reindex(u10.index).ffill()).dropna()
    sig["curve"] = (np.where(curve > 0, 1.0, -1.0), 2.0)  # +1 if >0 else -1 (never 0)

    stab = load("stablecoin_total_liquidity", col="total_cap_usd")
    g = stab / stab.shift(30) - 1
    sig["stablecoin"] = (bands(g, None, None, 0.02, -0.02), 2.0)

    sig["dxy"] = (slope(load("dxy")), 1.5)

    m2 = load("fred_us_m2", col="value")
    yoy = m2 / m2.shift(12) - 1
    sig["m2"] = (bands(yoy, None, None, 0.04, 0.01), 2.0)

    fbs = load("fred_fed_balance_sheet", col="value")
    chg = fbs / fbs.shift(60) - 1  # 60 rows on weekly file = 60 weeks (engine iloc[-61])
    sig["fed_bs"] = (bands(chg, None, None, 0.01, -0.01), 1.5)

    # B. RISK APPETITE
    vix = load("vix")
    sig["vix"] = (bands(vix, None, None, 20.0, 30.0), 1.5)  # <20 -> +1, >30 -> -1

    sig["spx"] = (slope(load("sp500")), 1.5)

    hy = load("fred_hy_spread", col="value")
    sig["credit"] = (bands(hy, None, None, 3.5, 5.5), 1.5)

    # C. CRYPTO INTERNAL
    sig["btc_ma"] = (slope(btc), 2.0)

    fng = load("fear_greed", col="value")
    sig["fng"] = (bands(fng, None, None, 30.0, 70.0), 1.0)

    hash_s = load("bi_hash-rate", "ts", "value")
    sig["hash"] = (slope(hash_s, 60), 0.5)

    # D. INFLATION / REAL
    ry = load("fred_real_yield10y", col="value")
    sig["real_yield"] = (bands(ry, None, None, 1.5, 2.5), 1.0)

    cpi = load("fred_cpi", col="value")
    cy = cpi / cpi.shift(12) - 1
    sig["cpi"] = (bands(cy, None, None, 0.03, 0.05), 0.5)

    sig["gold"] = (slope(load("gold")), 0.5)

    # Build daily score table
    WTS = {k: v for k, (_, v) in sig.items()}
    avail = {}
    for k, (s, w) in sig.items():
        if isinstance(s, np.ndarray):
            s = pd.Series(s, index=curve.index)
        avail[k] = s.reindex(idx).ffill()

    sig_df = pd.DataFrame(avail)
    wsum = (sig_df.notna() * pd.Series(WTS)).sum(axis=1)
    score = (sig_df.fillna(0) * pd.Series(WTS)).sum(axis=1) / wsum * 3

    # Baseline: 200d-MA filter only (same no-lookahead convention)
    ma200 = btc.rolling(200).mean()
    ma_sig = (btc >= ma200).astype(float)

    def simulate(in_market, name, hyst=None):
        """hyst: dict(entry=float, exit=float, days=int) - switch only after N consecutive days
        past the entry/exit threshold; else flip on next day (no-lookahead convention)."""
        if hyst:
            s = score.reindex(idx).ffill()
            raw = pd.Series(0.0, index=idx)
            raw[s >= hyst["entry"]] = 1.0
            raw[s <= hyst["exit"]] = 0.0
            state = raw.rolling(hyst["days"]).mean()  # fraction of last N days in market
            in_market = (state >= 0.5).astype(float)
        in_market = in_market.shift(1).fillna(1.0)  # decide with yesterday's data
        rets = btc.pct_change().fillna(0)
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

    results, eqs = [], {}
    runs = [
        ("v4_composite (score>=+0.5)", (score >= 0.5).astype(float), None),
        ("v4_composite (score>0)", (score > 0).astype(float), None),
        ("v4_composite (score>=-0.5)", (score >= -0.5).astype(float), None),
        ("v4_hyst (entry +0.5 exit -0.5, 3d)", None, {"entry": 0.5, "exit": -0.5, "days": 3}),
        ("v4_hyst (entry +0.5 exit -0.5, 5d)", None, {"entry": 0.5, "exit": -0.5, "days": 5}),
        ("200d_MA_filter", ma_sig, None),
    ]
    for label, cond, hyst in runs:
        r, eq = simulate(cond, label, hyst=hyst)
        results.append(r)
        eqs[label] = eq

    bh_eq = (1 + btc.pct_change().fillna(0)).cumprod() * 10000
    bh_dd = (bh_eq / bh_eq.cummax() - 1).min() * 100
    years = len(bh_eq) / 365.25
    results.append({
        "name": "buy_hold", "final": float(bh_eq.iloc[-1]), "pct": float((bh_eq.iloc[-1]/10000-1)*100),
        "cagr": float((bh_eq.iloc[-1]/10000)**(1/years)*100-100), "max_dd": float(bh_dd),
        "cash_days": 0, "flips": 0,
    })

    # Events: first day of each v4 in/out switch
    v4in = (score >= 0.5).astype(float)
    v4in_s = v4in.shift(1).fillna(1.0)
    chg = v4in_s.diff().fillna(0)
    events = []
    for t in chg[chg != 0].index:
        events.append({
            "date": str(t.date()), "to": "IN" if v4in_s[t] == 1 else "CASH",
            "score": round(float(score[t]), 2), "btc": round(float(btc[t])),
        })
    # Signal stats: availability + sign distribution in window
    sig_stats = {}
    for k in sig:
        s = sig_df[k]
        sig_stats[k] = {
            "available_days": int(s.notna().sum()),
            "pct_available": round(float(s.notna().mean() * 100), 1),
            "sign_dist": {"+1": int((s == 1).sum()), "0": int((s == 0).sum()), "-1": int((s == -1).sum())},
        }

    # Yearly returns (v4 headline, MA, BH)
    yearly = {}
    for label in ["v4_composite (score>=+0.5)", "200d_MA_filter"]:
        y = eqs[label].resample("YE").last().pct_change()
        y.iloc[0] = eqs[label].resample("YE").last().iloc[0] / 10000 - 1
        yearly[label] = {str(d.date())[:4]: round(float(v) * 100, 1) for d, v in y.items()}
    yb = bh_eq.resample("YE").last().pct_change()
    yb.iloc[0] = bh_eq.resample("YE").last().iloc[0] / 10000 - 1
    yearly["buy_hold"] = {str(d.date())[:4]: round(float(v) * 100, 1) for d, v in yb.items()}

    out = {
        "window": f"{W} -> {END}", "start_cash": 10000,
        "method": "signal at t-1 applied to return t; available-weight normalization; cash 0% yield",
        "results": results, "yearly": yearly,
        "flips": len(events), "events": events,
        "signal_stats": sig_stats,
        "caveats": [
            "HY credit spread only exists 2023-08+ (absent 2017-2022)",
            "F&G only 2018-05+; stablecoin liquidity 2017-11+",
            "Monthly CPI/M2 used as-of without publication lag (small lookahead on those two)",
            "Cash earns 0%; daily closes only; no slippage/fees",
            "fed_bs shift(60) = 60 rows on the WEEKLY file (~60 weeks), matching engine iloc[-61]",
        ],
    }
    with open(OUT / "v4_composite_backtest.json", "w") as f:
        json.dump(out, f, indent=2, default=float)

    # Console
    print(f"=== v4 COMPOSITE BACKTEST {W} -> {END} ($10k) ===\n")
    for r in results:
        print(f"{r['name']:28} ${r['final']:>14,.0f}  {r['pct']:>+11,.0f}%  CAGR {r['cagr']:>+7.1f}%  MaxDD {r['max_dd']:>6.1f}%  cash {r['cash_days']}d  flips {r['flips']}")
    print("\nYearly returns %:")
    yrs = sorted({y for d in yearly.values() for y in d})
    print(f"{'year':6} {'v4':>8} {'MA200':>8} {'BH':>8}")
    for y in yrs:
        print(f"{y:6} {yearly['v4_composite (score>=+0.5)'].get(y, float('nan')):>8.1f} {yearly['200d_MA_filter'].get(y, float('nan')):>8.1f} {yearly['buy_hold'].get(y, float('nan')):>8.1f}")
    print(f"\nRegime switches ({len(events)}):")
    for e in events:
        print(f"  {e['date']}  {e['to']:>4}  score {e['score']:+.2f}  BTC ${e['btc']:,}")
    print(f"\nSaved -> {OUT/'v4_composite_backtest.json'}")


if __name__ == "__main__":
    main()
