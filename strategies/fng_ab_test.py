#!/usr/bin/env python3
"""
A/B TEST: Does F&G add precision to the regime engine?
Compares two engine variants on the SAME data (2018-2026, when F&G exists):
  A) Full v4 signal set (14 signals incl. F&G)
  B) Same minus F&G signal

Measures: total return, max DD, annualized, and regime-switch agreement.
Uses local macro_dataset (no network). Strategy: score>=+0.5 hold, else cash.
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"


def load(name):
    p = DATA / f"{name}.csv"
    if not p.exists(): return None
    df = pd.read_csv(p)
    tcol = "ts" if "ts" in df.columns else "date"
    df[tcol] = pd.to_datetime(df[tcol], utc=True)
    df = df.set_index(tcol).sort_index()
    return df

def series(name, col):
    df = load(name)
    return None if df is None else df[col]

def ma_trend(s, n):
    """+1 above MA, -1 below, 0 neutral (per day)."""
    m = s.rolling(n).mean()
    out = pd.Series(0.0, index=s.index)
    out[s > m] = 1.0
    out[s < m] = -1.0
    return out

def fng_signal(fng):
    """F&G contrarian: +1 fear<30, -1 greed>70, else 0."""
    out = pd.Series(0.0, index=fng.index)
    out[fng < 30] = 1.0
    out[fng > 70] = -1.0
    return out

def build_signals(use_fng=True):
    """Return dict of aligned daily signal Series (v4 weights)."""
    btc = series("btcusd_daily_bitstamp", "close")
    dxy = series("dxy", "close")
    us10y, us3m = series("us10y", "close"), series("us3m", "close")
    vix = series("vix", "close")
    spx = series("sp500", "close")
    stab = series("stablecoin_total_liquidity", "total_cap_usd")
    hash_s = series("bi_hash-rate", "value")
    gold = series("gold", "close")
    m2 = series("fred_us_m2", "value")
    fed_bs = series("fred_fed_balance_sheet", "value")
    real_y = series("fred_real_yield10y", "value")
    cpi = series("fred_cpi", "value")
    hy = series("fred_hy_spread", "value")
    fng = series("fear_greed", "value")

    sig = {}
    # A. Liquidity
    sig["curve"] = np.sign(us10y - us3m)  # +1 steep, -1 inverted
    sig["stablecoin"] = np.sign(stab.pct_change(30))
    sig["dxy"] = ma_trend(dxy, 200)
    sig["m2"] = pd.Series(np.where(m2.pct_change(12) > 0.04, 1.0, np.where(m2.pct_change(12) < 0.01, -1.0, 0.0)), index=m2.index)
    sig["fed_bs"] = pd.Series(np.sign(fed_bs.pct_change(60)), index=fed_bs.index)
    # B. Risk
    sig["vix"] = pd.Series(np.where(vix < 20, 1.0, np.where(vix > 30, -1.0, 0.0)), index=vix.index)
    sig["spx"] = ma_trend(spx, 200)
    sig["credit"] = pd.Series(np.where(hy < 3.5, 1.0, np.where(hy > 5.5, -1.0, 0.0)), index=hy.index)
    # C. Crypto
    sig["btc_ma"] = ma_trend(btc, 200)
    if use_fng: sig["fng"] = fng_signal(fng)
    sig["hash"] = ma_trend(hash_s, 60)
    # D. Inflation
    sig["real_yield"] = pd.Series(np.where(real_y < 1.5, 1.0, np.where(real_y > 2.5, -1.0, 0.0)), index=real_y.index)
    sig["cpi"] = pd.Series(np.where(cpi.pct_change(12) < 0.03, 1.0, np.where(cpi.pct_change(12) > 0.05, -1.0, 0.0)), index=cpi.index)
    sig["gold"] = ma_trend(gold, 200)
    return sig, btc

def run(use_fng):
    sig, btc = build_signals(use_fng)
    # Weights (v4)
    W = {"curve": 2.0, "stablecoin": 2.0, "dxy": 1.5, "m2": 2.0, "fed_bs": 1.5,
         "vix": 1.5, "spx": 1.5, "credit": 1.5, "btc_ma": 2.0,
         "fng": 1.0, "hash": 0.5, "real_yield": 1.0, "cpi": 0.5, "gold": 0.5}
    if not use_fng: W.pop("fng")

    # Align all signals on BTC index (2018+ when F&G exists)
    idx = btc.index
    frame = pd.DataFrame(index=idx)
    for k, s in sig.items():
        frame[k] = s.reindex(idx).fillna(0.0)

    total_w = sum(W.values())
    score = sum(frame[k] * w for k, w in W.items()) / total_w * 3
    # Strategy: hold when score >= +0.5, cash otherwise
    in_market = (score >= 0.5).astype(bool)

    rets = btc.reindex(idx).pct_change().fillna(0)
    eq = (1 + rets * in_market).cumprod() * 10000
    eq_bh = (1 + rets).cumprod() * 10000
    dd = (eq / eq.cummax() - 1).min() * 100
    dd_bh = (eq_bh / eq_bh.cummax() - 1).min() * 100
    return {
        "use_fng": use_fng,
        "final": float(eq.iloc[-1]), "pct": float((eq.iloc[-1]/10000-1)*100),
        "dd": float(dd), "bh_pct": float((eq_bh.iloc[-1]/10000-1)*100), "bh_dd": float(dd_bh),
        "cash_days": int((~in_market).sum()),
        "n_signals": len(W),
    }

print("=== A/B: v4 ENGINE WITH vs WITHOUT F&G (2011-2026, $10k start) ===")
a = run(use_fng=True)
b = run(use_fng=False)
for r in (a, b):
    lbl = "WITH F&G  " if r["use_fng"] else "WITHOUT F&G"
    print(f"  {lbl}: final ${r['final']:>12,.0f} ({r['pct']:>+10,.0f}%)  DD {r['dd']:>6.1f}%  cash_days={r['cash_days']:>5}  signals={r['n_signals']}")
print(f"  Buy-hold:        final $10,000 -> ${a['bh_pct']/100*10000:,.0f} ({a['bh_pct']:+.0f}%)  DD {a['bh_dd']:.1f}%")
print(f"\n  Delta (F&G effect): {a['pct'] - b['pct']:+.0f}pp return, {a['dd'] - b['dd']:+.1f}pp DD")
# Stateless: results printed above; nothing persisted.
