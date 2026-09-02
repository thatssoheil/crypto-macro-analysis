#!/usr/bin/env python3
"""
GOLD LEAD-TIME STUDY: does gold LEAD BTC cycle tops (like M2/DXY) or lag them?
Methodology mirrors lead_time_analysis.py conventions:
  - negative lead  = signal fired BEFORE the top (real warning)
  - positive lead  = fired AFTER (reaction, useless as a warning)
Deterministic gold signals (no subjective labels):
  G1 gold < 200d MA (first daily close below after having been above)
  G2 gold 60d ROC peak rollover (ROC was rising, peaks, falls >0.5*atr for 10d)
  G3 gold 200d MA slope turns negative (20d change of the MA < 0)
  G4 gold/BTC ratio top (ratio peak in window - capital rotating OUT of BTC)
Plus a FALSE-POSITIVE scan: every G1/G3 event 2012-2026 -> BTC forward 90d return.
Plus an A/B GATE backtest: 200d-MA filter vs filter-that-refuses-entry-when-gold-
below-200d-MA (shift(1), cash 0%, $10k, 2012-2026 - gold 200MA valid from 2012-06).
Stateless: prints to stdout, saves nothing.
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"

def load(name):
    df = pd.read_csv(DATA / f"{name}.csv")
    tcol = "ts" if "ts" in df.columns else "date"
    df[tcol] = pd.to_datetime(df[tcol], utc=True)
    return df.set_index(tcol).sort_index()

btc = load("btcusd_daily_bitstamp")["close"]
gold = load("gold")["close"]
# align on common index (gold is FX-ish daily; btc daily)
common = btc.index.intersection(gold.index)
btc, gold = btc.loc[common], gold.loc[common]

gma = gold.rolling(200).mean()
groc60 = gold.pct_change(60)
gma_slope20 = gma.pct_change(20)
gbtc = gold / btc  # ratio: rising = money hiding in gold, falling = BTC outperformance

# ---- signal event series (True = fired that day, state-change detection) ----
above = gold > gma
g1 = above.shift(1).fillna(False) & ~above & gma.notna()          # cross BELOW 200MA
g3 = (gma_slope20 < 0) & (gma_slope20.shift(1) >= 0) & gma.notna()  # MA slope turns negative
# G2: 60d ROC rollover - ROC peak >=5%, then drops >2pp from its trailing 30d max
roc_peak_max = groc60.rolling(30).max()
g2 = (groc60 <= roc_peak_max - 0.02) & (roc_peak_max.shift(1) >= 0.05) & (groc60 > roc_peak_max.shift(1) - 0.02) & groc60.notna()

def first_after(mask, t0):
    s = mask.loc[t0:]
    s = s[s]
    return s.index[0] if len(s) else None

TOPS = [
    ("2013 top", "2013-01-01", "2014-06-01"),
    ("2017 top", "2017-01-01", "2018-06-01"),
    ("2021 top", "2021-01-01", "2022-06-01"),
]

print("=== PART 1: LEAD TIMES vs BTC CYCLE TOPS ===")
for label, lo, hi in TOPS:
    win = btc.loc[lo:hi]
    top_date = win.idxmax()
    top_px = win.max()
    print(f"\n{label}: BTC ATH {top_date.date()} (${top_px:,.0f})")
    for nm, mask in [("G1 gold<200MA", g1), ("G2 ROC60 rollover", g2), ("G3 200MA slope<0", g3)]:
        d = first_after(mask, top_date)
        if d is None:
            print(f"  {nm:18s} no event after top in data")
            continue
        lead = (top_date - d).days
        g_at = gold.loc[d]
        print(f"  {nm:18s} {d.date()}  {-lead:+d} days vs top  (gold ${g_at:,.0f}, BTC at that day ${btc.loc[d]:,.0f})")
    # G4: where did gold/BTC ratio PEAK relative to the top
    r = gbtc.loc[lo:hi]
    if len(r):
        rpk = r.idxmax()
        rel = (top_date - rpk).days
        print(f"  {'G4 gold/BTC peak':18s} {rpk.date()}  {-rel:+d} days vs top  (ratio {r.max():.4f}; now {gbtc.iloc[-1]:.4f})")

print("\n=== PART 2: FALSE-POSITIVE SCAN (every G1 event, BTC fwd returns) ===")
events = g1[g1].index
n_decline = 0
for d in events:
    fwd = btc.loc[d:].iloc[:91]
    if len(fwd) < 30:
        continue
    r90 = (fwd.iloc[-1] / btc.loc[d] - 1) * 100
    # did BTC top (local max >=20% above event px within 90d before event)?
    prior = btc.loc[:d].iloc[-91:]
    local_top = (prior.max() / btc.loc[d] - 1) * 100  # how far below the recent high
    bear_soon = btc.loc[d:d + pd.Timedelta(days=180)].min() / btc.loc[d] - 1
    flag = "BEAR-FOLLOWED" if bear_soon < -0.25 else ""
    if flag: n_decline += 1
    print(f"  G1 {d.date()}  gold ${gold.loc[d]:,.0f}  fwd90d {r90:+.1f}%  min180d {bear_soon*100:+.1f}% {flag}")
print(f"  -> {n_decline}/{len(events)} G1 events preceded a >25% BTC decline within 180d")

print("\n=== PART 3: A/B GATE BACKTEST (2012-2026, shift(1), cash 0%) ===")
df = pd.DataFrame({"btc": btc, "gold": gold, "gma": gma}).dropna()
px, gld, g200 = df["btc"], df["gold"], df["gma"]
ret = px.pct_change().fillna(0)
btc_above = px > px.rolling(200).mean()
base_pos = btc_above.shift(1).fillna(False)                 # trend filter alone
gated_pos = (btc_above & (gld > g200)).shift(1).fillna(False)  # + gold regime gate

def stats(pos, name):
    eq = (1 + ret * pos).cumprod()
    yrs = len(eq) / 365.25
    dd = (eq / eq.cummax() - 1).min()
    flips = int(pos.astype(int).diff().abs().sum())
    print(f"  {name:34s} total {(eq.iloc[-1]-1)*100:+12.0f}%  CAGR {(eq.iloc[-1]**(1/yrs)-1)*100:+.1f}%  maxDD {dd*100:.1f}%  flips {flips}")
    return eq

stats(base_pos, "200d MA filter (baseline)")
stats(gated_pos, "200d MA AND gold>200MA (gate)")
stats(pd.Series(True, index=ret.index), "buy_hold")

print("\n=== PART 4: WHAT GOLD IS DOING NOW (2026-08-28) ===")
print(f"  gold ${gold.iloc[-1]:,.0f} vs 200MA ${gma.iloc[-1]:,.0f}  ({(gold.iloc[-1]/gma.iloc[-1]-1)*100:+.1f}%)")
print(f"  gold 60d ROC {groc60.iloc[-1]*100:+.1f}% | 200MA slope20 {gma_slope20.iloc[-1]*100:+.2f}%")
print(f"  gold/BTC {gbtc.iloc[-1]:.4f}  30d {gbtc.iloc[-1]/gbtc.iloc[-30]-1:+.1%}  90d {gbtc.iloc[-1]/gbtc.iloc[-90]-1:+.1%} (rising = money hiding in gold)")
last_g1 = events[-1] if len(events) else None
print(f"  last G1 (gold<200MA) event: {last_g1.date() if last_g1 is not None else 'never'}")
