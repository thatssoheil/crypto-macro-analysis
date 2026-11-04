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
    # auto-detect time column (some charts use 'ts', others 'date'; the 15m
    # Binance research charts use 'open_time' as epoch milliseconds)
    tcol = next((c for c in ("ts", "date", "open_time") if c in df.columns), None)
    if tcol:
        col = df[tcol]
        if pd.api.types.is_numeric_dtype(col):
            unit = "ms" if float(col.iloc[-1]) > 1e11 else "s"
            col = pd.to_datetime(col, unit=unit, utc=True)
        else:
            col = pd.to_datetime(col, utc=True)
        df[tcol] = col
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
    # Hardened 2026-10-18: one bad chart (half-written CSV, unparseable
    # time col) must not kill the whole weekly audit - record CHECK and
    # continue, same fail-soft family as the fetcher keeping old-but-valid
    # files on network blips.
    try:
        if not isinstance(idx, pd.DatetimeIndex):
            idx = pd.to_datetime(idx, utc=True)
        gaps = (idx.to_series().diff().dt.days).dropna()
    except Exception as e:
        print(f"  {name:40s} rows={len(df):>7} AUDIT-ERROR {e} CHECK")
        problems.append(name)
        continue
    allowed = 45 if name in MONTHLY else 10
    if name == "fred_rrp":
        # RRP operations were sparse before the facility went daily (2013-14);
        # judge only the dense era - zero gaps there since.
        gaps = gaps[gaps.index >= pd.Timestamp("2014-01-01", tz="UTC")]
    if name in ("bn_lsr_btc", "bn_lsr_eth", "bn_taker_btc", "bn_taker_eth"):
        # Binance's archive has empty top-trader/taker fields for much of 2022
        # (source-side, documented in SOURCES.md); judge the clean era only.
        gaps = gaps[gaps.index >= pd.Timestamp("2023-01-01", tz="UTC")]
    big_gaps = (gaps > allowed).sum() if len(gaps) else 0
    # 2. duplicate timestamps
    dups = idx.duplicated().sum()
    # 3. nulls
    nulls = int(df.isnull().sum().sum())
    if name == "bn_metrics_15m_btc":
        # Binance serves empty top-trader/taker ratio fields on scattered days
        # (source-side; same quirk family as bn_lsr/bn_taker) - those columns'
        # blanks are known, the null watch stays on the price/OI columns.
        _known = [c for c in ("count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
                              "count_long_short_ratio", "sum_taker_long_short_vol_ratio") if c in df.columns]
        nulls -= int(df[_known].isnull().sum().sum())
    # 4. sanity: negative allowed for real-yield, us3m, wti (historical events)
    #    for the signed on-chain flow charts (an outflow IS negative) and for
    #    NUPL, which goes negative in bear phases by definition
    neg_ok = name in ("fred_real_yield10y", "us3m", "wti", "gn_exchange_netflow_btc",
                      "gn_exchange_netflow_eth", "gn_nupl", "gn_nupl_eth",
                      "gn_exchange_netflow_btc_pit", "gn_exchange_netflow_eth_pit",
                      "gn_nupl_pit", "gn_nupl_eth_pit",
                      # 2026-09-24 flow-semantics + ETF additions with legit negatives
                      "gn_hodler_npc_btc", "gn_hodler_npc_btc_pit",
                      "gn_hodler_npc_eth", "gn_hodler_npc_eth_pit",
                      "gn_net_realized_pl", "gn_net_realized_pl_pit",
                      "gn_net_realized_pl_eth", "gn_net_realized_pl_eth_pit",
                      "gn_etf_flows_net_btc", "gn_etf_flows_net_btc_pit",
                      "gn_etf_flows_net_eth", "gn_etf_flows_net_eth_pit",
                      # 2026-09-24 derivatives: funding is signed
                      "bn_funding_btc", "bn_funding_eth")
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

# --- TRAILING AGE (added 2026-11-04) -------------------------------------------------
# The gap checks above measure gaps BETWEEN rows, so a series that simply STOPS has no
# trailing gap and reads as healthy forever. This block makes the age of the last
# observation explicit, which is the only thing that catches a dead feed.
FRESH = {"monthly": 75, "weekly": 14, "daily": 10}
MONTHLY_SET = {"fred_cpi", "fred_pce", "fred_unemployment", "fred_us_m2", "fred_nonfarm_payrolls"}
WEEKLY_SET = {"fred_fed_balance_sheet", "fred_tga", "fred_rrp", "fred_jobless_claims"}
now = pd.Timestamp.now(tz="UTC")
stale, frozen = [], []
for name in charts:
    df = load(name)
    if df is None or len(df) == 0:
        continue
    limit = (FRESH["monthly"] if name in MONTHLY_SET
             else FRESH["weekly"] if name in WEEKLY_SET else FRESH["daily"])
    age = (now - df.index[-1]).days
    if age > limit:
        # The on-chain family is INTENTIONALLY frozen: keyless Glassnode access ended
        # 2026-10-01 and the paid route was declined. Report it, never fail on it.
        (frozen if name.startswith("gn_") else stale).append((name, age, limit))
print(f"\n  Stale inputs (older than their cadence allows): {len(stale)}")
for name, age, limit in sorted(stale, key=lambda r: -r[1]):
    print(f"    STALE {name:40s} last={age:>4}d ago (limit {limit}d)")
print(f"  Frozen by owner decision (expected): {len(frozen)}")
if frozen:
    print(f"    FROZEN on-chain family, oldest row {max(f[1] for f in frozen)}d old"
          f" - historical only, never quote as a live read")
if stale:
    problems.extend(n for n, _, _ in stale)

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
    # Fixed 2026-11-04: this asserted spread > 0, so a legitimate curve inversion FAILED
    # and a 100x unit error PASSED. Validate magnitude, and report the shape separately.
    chk("curve", -5 < spread < 10,
        f"10y-3m = {us10y['close'].iloc[-1]:.2f} - {us3m['close'].iloc[-1]:.2f} = {spread:.2f}%"
        f" ({'inverted' if spread < 0 else 'positive'})")
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
    # Fixed 2026-11-04: was an unconditional True, i.e. not a check at all.
    chk("spx", 300 < spx["close"].iloc[-1] < 30_000,
        f"SPX {spx['close'].iloc[-1]:,.0f} {'>' if above else '<'} 200MA {ma:,.0f}")
if hy is not None:
    hyv = hy["value"].iloc[-1]
    chk("credit", 0.5 < hyv < 15, f"HY spread = {hyv:.2f}%")

# C. Crypto
if btc is not None:
    ma = btc["close"].rolling(200).mean().iloc[-1]
    above = btc["close"].iloc[-1] > ma
    # Fixed 2026-11-04: was an unconditional True, i.e. not a check at all.
    chk("btc_ma", 1_000 < btc["close"].iloc[-1] < 2_000_000,
        f"BTC {btc['close'].iloc[-1]:,.0f} {'>' if above else '<'} 200MA {ma:,.0f}")
if fng is not None:
    f = int(fng["value"].iloc[-1])
    chk("fng", 0 <= f <= 100, f"F&G = {f}")
if hash_df is not None:
    hd = hash_df.rename(columns={"value": "close"})
    ma = hd["close"].rolling(60).mean().iloc[-1]
    above = hd["close"].iloc[-1] > ma
    # Fixed 2026-11-04: was an unconditional True, i.e. not a check at all.
    chk("hash", 1e5 < hd["close"].iloc[-1] < 1e12,
        f"hash {hd['close'].iloc[-1]:,.0f} {'>' if above else '<'} 60MA {ma:,.0f}")

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

# 2026-09-24 source-hunt additions - loose last-value sanity bands (catch a bad
# merge or a unit change loudly; sanity floors, not precision bands).
_EXTRA = [
    ("gn_hodler_npc_btc",      lambda v: abs(v) < 300_000,    "{:+,.0f} coins"),
    ("gn_hodler_npc_eth",      lambda v: abs(v) < 5_000_000,  "{:+,.0f} coins"),
    ("gn_net_realized_pl",     lambda v: abs(v) < 5e10,       "{:+,.0f} USD"),
    ("gn_net_realized_pl_eth", lambda v: abs(v) < 5e10,       "{:+,.0f} USD"),
    ("gn_sopr_adjusted",       lambda v: 0.5 < v < 3,         "{:.3f}"),
    ("gn_sopr_155d",           lambda v: 0.3 < v < 6,         "{:.3f}"),
    ("gn_whales_to_exchanges", lambda v: 0 <= v < 2_000_000,  "{:,.0f}"),
    ("gn_exchanges_to_whales", lambda v: 0 <= v < 2_000_000,  "{:,.0f}"),
    ("gn_reshuffling_ratio",   lambda v: 0 <= v <= 1,         "{:.3f}"),
    ("gn_etf_flows_net_btc",   lambda v: abs(v) < 1_000_000,  "{:+,.0f}"),
    ("gn_etf_flows_net_eth",   lambda v: abs(v) < 20_000_000, "{:+,.0f}"),
    # 2026-09-24 liquidity batch (FRED/FiscalData - loose unit-agnostic floors)
    ("fred_rrp",               lambda v: 0 <= v < 3e6,        "{:,.3f}"),
    ("fred_tga",               lambda v: 0 < v < 3e6,         "{:,.0f}"),
    ("tga_daily",              lambda v: 0 < v < 3e6,         "{:,.0f}"),
    # 2026-09-24 derivatives batch (Deribit DVOL + Binance archive)
    ("dvol_btc",               lambda v: 5 < v < 300,         "{:.1f}"),
    ("dvol_eth",               lambda v: 5 < v < 300,         "{:.1f}"),
    ("bn_oi_btc",              lambda v: 0 < v < 2_000_000,   "{:,.0f}"),
    ("bn_oi_eth",              lambda v: 0 < v < 50_000_000,  "{:,.0f}"),
    ("bn_lsr_btc",             lambda v: 0.1 < v < 10,        "{:.3f}"),
    ("bn_lsr_eth",             lambda v: 0.1 < v < 10,        "{:.3f}"),
    ("bn_taker_btc",           lambda v: 0.1 < v < 10,        "{:.3f}"),
    ("bn_taker_eth",           lambda v: 0.1 < v < 10,        "{:.3f}"),
    ("bn_funding_btc",         lambda v: -0.01 < v < 0.01,    "{:.6f}"),
    ("bn_funding_eth",         lambda v: -0.01 < v < 0.01,    "{:.6f}"),
    # 2026-09-27 batch 2 (Binance gross exchange flows; non-negative gross)
    ("gn_binance_inflow_btc",  lambda v: 0 <= v < 1_000_000,   "{:,.0f}"),
    ("gn_binance_outflow_btc", lambda v: 0 <= v < 1_000_000,   "{:,.0f}"),
    ("gn_binance_inflow_eth",  lambda v: 0 <= v < 5_000_000,   "{:,.0f}"),
    ("gn_binance_outflow_eth", lambda v: 0 <= v < 5_000_000,   "{:,.0f}"),
]
for _n, _band, _fmt in _EXTRA:
    _d = load(_n)
    if _d is None:
        continue
    _v = float(_d["value"].iloc[-1])
    chk(_n, _band(_v), "last = " + _fmt.format(_v))

# Charts the engine actually consumes. A stale one of these can invert a verdict, so it
# fails the audit. A stale chart outside this set is reported and warns, but does not
# block: the frozen on-chain layer already proves a non-engine feed can die quietly.
ENGINE_INPUTS = {
    "us10y", "us3m", "dxy", "vix", "sp500", "gold", "stablecoin_total_liquidity",
    "fred_us_m2", "fred_fed_balance_sheet", "fred_hy_spread", "btcusd_daily_bitstamp",
    "fear_greed", "bi_hash-rate", "fred_real_yield10y", "fred_cpi",
}
stale_core = [s for s in stale if s[0] in ENGINE_INPUTS]
stale_other = [s for s in stale if s[0] not in ENGINE_INPUTS]

print()
fails = [c for c in checks if not c[1]]
print(f"  SIGNAL CHECKS: {len(checks)-len(fails)}/{len(checks)} pass, {len(fails)} fail")
for name, cond, detail in fails:
    print(f"    FAIL {name}: {detail}")
print(f"  STALE ENGINE INPUTS: {len(stale_core)}")
for name, age, limit in sorted(stale_core, key=lambda r: -r[1]):
    print(f"    STALE {name}: {age}d (limit {limit}d)  <- blocks the verdict")
print(f"  STALE NON-ENGINE CHARTS (warn only): {len(stale_other)}")
for name, age, limit in sorted(stale_other, key=lambda r: -r[1]):
    print(f"    WARN  {name}: {age}d (limit {limit}d)")

# Fixed 2026-11-04: the audit used to exit 0 no matter what it found, so it could report
# failures and still certify the run.
if fails or stale_core:
    print("  AUDIT RESULT: FAIL (structural)")
    raise SystemExit(1)
print("  AUDIT RESULT: PASS")
