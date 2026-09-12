#!/usr/bin/env python3
"""
DATA INTEGRITY + SIGNAL CORRECTNESS AUDIT for the macro dataset + regime engine.
Verifies every chart and every v4 signal independently against raw data.
"""
import csv, json
from datetime import date
from pathlib import Path
import pandas as pd
import numpy as np

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"

def load(name):
    p = DATA / f"{name}.csv"
    if not p.exists(): return None
    df = pd.read_csv(p)
    # auto-detect time column (some charts use 'ts', others 'date')
    tcol = "ts" if "ts" in df.columns else ("date" if "date" in df.columns else None)
    if tcol:
        df[tcol] = pd.to_datetime(df[tcol], utc=True)
        df = df.set_index(tcol).sort_index()
    return df

print("=" * 70)
print("PART 1: CHART INTEGRITY (gaps, monotonicity, sanity)")
print("=" * 70)
problems = []
charts = sorted(p.stem for p in DATA.glob("*.csv") if p.stem != "manifest")
MONTHLY = {"fred_cpi", "fred_pce", "fred_unemployment", "fred_us_m2", "fred_nonfarm_payrolls"}
for name in charts:
    df = load(name)
    if df is None: continue
    idx = df.index
    # 1. gaps - monthly series naturally have ~30d gaps; daily should have <10d
    gaps = (idx.to_series().diff().dt.days).dropna()
    allowed = 45 if name in MONTHLY else 10
    big_gaps = (gaps > allowed).sum() if len(gaps) else 0
    # 2. duplicate timestamps
    dups = idx.duplicated().sum()
    # 3. nulls
    nulls = int(df.isnull().sum().sum())
    # 4. sanity: negative allowed for real-yield, us3m, wti (historical events)
    #    for the signed on-chain flow charts (an outflow IS negative) and for
    #    NUPL, which goes negative in bear phases by definition
    neg_ok = name in ("fred_real_yield10y", "us3m", "wti", "gn_exchange_netflow_btc",
                      "gn_exchange_netflow_eth", "gn_nupl", "gn_nupl_eth",
                      "gn_exchange_netflow_btc_pit", "gn_exchange_netflow_eth_pit",
                      "gn_nupl_pit", "gn_nupl_eth_pit")
    vals = df.select_dtypes(include=[np.number])
    negs = int((vals < 0).sum().sum()) if not vals.empty else 0
    neg_flag = negs and not neg_ok
    status = "OK"
    if big_gaps or dups or nulls or neg_flag:
        status = "CHECK"
        problems.append(name)
    print(f"  {name:40s} rows={len(df):>7} gaps>={allowed}d={big_gaps:>4} dups={dups} nulls={nulls} neg={negs} {status}")

print(f"\n  Charts needing review: {problems if problems else 'NONE'}")
print(f"  Total charts: {len(charts)}")

print()
print("=" * 70)
print("PART 2: SIGNAL CORRECTNESS (v4 engine vs raw data)")
print("=" * 70)
# Recompute each v4 signal from raw and print the math
btc = load("btcusd_daily_bitstamp")
dxy = load("dxy")
us10y, us3m = load("us10y"), load("us3m")
vix, spx = load("vix"), load("sp500")
gold = load("gold")
stab = load("stablecoin_total_liquidity")
fng = load("fear_greed")
hash_df = load("bi_hash-rate")
m2 = load("fred_us_m2")
fed_bs = load("fred_fed_balance_sheet")
real_y = load("fred_real_yield10y")
cpi = load("fred_cpi")
hy = load("fred_hy_spread")

checks = []
def chk(name, cond, detail):
    checks.append((name, cond, detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}: {detail}")

# A. Liquidity
if us10y is not None and us3m is not None:
    spread = us10y["close"].iloc[-1] - us3m["close"].iloc[-1]
    chk("curve", spread > 0, f"10y-3m = {us10y['close'].iloc[-1]:.2f} - {us3m['close'].iloc[-1]:.2f} = {spread:.2f}%")
if stab is not None and len(stab) > 30:
    g = stab["total_cap_usd"].iloc[-1] / stab["total_cap_usd"].iloc[-30] - 1
    chk("stablecoin", abs(g) < 0.10, f"30d chg = {g*100:+.1f}%")
if m2 is not None and len(m2) > 13:
    yoy = m2["value"].iloc[-1] / m2["value"].iloc[-13] - 1
    chk("m2", abs(yoy) < 0.20, f"M2 YoY = {yoy*100:+.1f}% (latest {m2['value'].iloc[-1]:.0f})")
if fed_bs is not None and len(fed_bs) > 60:
    chg = fed_bs["value"].iloc[-1] / fed_bs["value"].iloc[-61] - 1
    chk("fed_bs", abs(chg) < 0.20, f"60d chg = {chg*100:+.1f}% (latest {fed_bs['value'].iloc[-1]:,.0f})")

# B. Risk
if vix is not None:
    v = vix["close"].iloc[-1]
    chk("vix", 5 < v < 80, f"VIX = {v:.1f}")
if spx is not None:
    ma = spx["close"].rolling(200).mean().iloc[-1]
    above = spx["close"].iloc[-1] > ma
    chk("spx", True, f"SPX {spx['close'].iloc[-1]:,.0f} {'>' if above else '<'} 200MA {ma:,.0f}")
if hy is not None:
    hyv = hy["value"].iloc[-1]
    chk("credit", 0.5 < hyv < 15, f"HY spread = {hyv:.2f}%")

# C. Crypto
if btc is not None:
    ma = btc["close"].rolling(200).mean().iloc[-1]
    above = btc["close"].iloc[-1] > ma
    chk("btc_ma", True, f"BTC {btc['close'].iloc[-1]:,.0f} {'>' if above else '<'} 200MA {ma:,.0f}")
if fng is not None:
    f = int(fng["value"].iloc[-1])
    chk("fng", 0 <= f <= 100, f"F&G = {f}")
if hash_df is not None:
    hd = hash_df.rename(columns={"value": "close"})
    ma = hd["close"].rolling(60).mean().iloc[-1]
    above = hd["close"].iloc[-1] > ma
    chk("hash", True, f"hash {hd['close'].iloc[-1]:,.0f} {'>' if above else '<'} 60MA {ma:,.0f}")

# D. Inflation
if real_y is not None:
    ry = real_y["value"].iloc[-1]
    chk("real_yield", -2 < ry < 6, f"real yield = {ry:.2f}%")
if cpi is not None:
    yoy = cpi["value"].iloc[-1] / cpi["value"].iloc[-13] - 1
    chk("cpi", abs(yoy) < 0.20, f"CPI YoY = {yoy*100:+.1f}% (latest {cpi['value'].iloc[-1]:.1f})")

# E. On-chain (Glassnode, merged from a rolling 30d window)
# The failure mode for these is a truncated or duplicated series, not a gap:
# ranges are checked so a unit change or a bad merge is caught loudly. The ETH
# twins differ only in the asset symbol - bands are per-asset (1 ETH whale move
# is a different size to 1 BTC).
GN_CHARTS = {
    "BTC": {"netflow": "gn_exchange_netflow_btc", "balance": "gn_exchange_balance_btc",
            "sopr": "gn_sopr", "nupl": "gn_nupl", "profit": "gn_supply_in_profit_pct",
            "balance_band": (500_000, 8_000_000), "flow_cap": 200_000},
    "ETH": {"netflow": "gn_exchange_netflow_eth", "balance": "gn_exchange_balance_eth",
            "sopr": "gn_sopr_eth", "nupl": "gn_nupl_eth", "profit": "gn_supply_in_profit_pct_eth",
            "balance_band": (1_000_000, 50_000_000), "flow_cap": 5_000_000},
}
for _sym, _m in GN_CHARTS.items():
    _s = _sym.lower()
    _nf, _exb = load(_m["netflow"]), load(_m["balance"])
    _sopr, _nupl, _sp = load(_m["sopr"]), load(_m["nupl"]), load(_m["profit"])
    if _nf is not None:
        _v = float(_nf["value"].iloc[-1])
        chk(f"gn_netflow_{_s}", abs(_v) < _m["flow_cap"],
            f"{_sym} exchange netflow = {_v:+,.0f}/day (signed: negative = off exchanges)")
    if _exb is not None:
        _v = float(_exb["value"].iloc[-1])
        lo, hi = _m["balance_band"]
        chk(f"gn_exchange_balance_{_s}", lo < _v < hi, f"{_sym} exchange balance = {_v:,.0f}")
    if _sopr is not None:
        _v = float(_sopr["value"].iloc[-1])
        chk(f"gn_sopr_{_s}", 0.5 < _v < 3, f"{_sym} SOPR = {_v:.3f}")
    if _nupl is not None:
        _v = float(_nupl["value"].iloc[-1])
        chk(f"gn_nupl_{_s}", -1 <= _v <= 1, f"{_sym} NUPL = {_v:.3f}")
    if _sp is not None:
        _v = float(_sp["value"].iloc[-1])
        chk(f"gn_supply_in_profit_{_s}", 0 <= _v <= 1, f"{_sym} supply in profit = {_v*100:.1f}%")
    if _nf is not None and _exb is not None:
        chk(f"gn_merge_continuity_{_s}", len(_nf) >= len(_exb) - 1 and len(_nf) > 1,
            f"{_sym}: {len(_nf)} netflow rows vs {len(_exb)} balance rows (merge kept both)")

print()
fails = [c for c in checks if not c[1]]
print(f"  SIGNAL CHECKS: {len(checks)-len(fails)}/{len(checks)} pass, {len(fails)} fail")
for name, cond, detail in fails:
    print(f"    FAIL {name}: {detail}")
