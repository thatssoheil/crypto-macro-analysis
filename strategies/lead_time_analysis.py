#!/usr/bin/env python3
"""
LEAD-TIME ANALYSIS: How much warning did each signal give before major BTC tops?
For each cycle top, measures when each signal fired relative to the ATH:
  negative = fired BEFORE the top (real warning), positive = AFTER (reaction).
Signals: current-engine exit (BTC < 200MA), M2 YoY peak, curve inversion,
stablecoin peak, DXY 200MA reclaim, F&G <= 30 (fear capitulation).
"""
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"

def load(name):
    df = pd.read_csv(DATA / f"{name}.csv")
    tcol = "ts" if "ts" in df.columns else "date"
    df[tcol] = pd.to_datetime(df[tcol], utc=True)
    return df.set_index(tcol).sort_index()

btc = load("btcusd_daily_bitstamp")["close"]
ma200 = btc.rolling(200).mean()
m2 = load("fred_us_m2")["value"]
m2_yoy = m2.pct_change(12)
us10y = load("us10y")["close"]
us3m = load("us3m")["close"]
spread = us10y - us3m
dxy = load("dxy")["close"]
dxy_ma = dxy.rolling(200).mean()
stab = load("stablecoin_total_liquidity")["total_cap_usd"]
fng = load("fear_greed")["value"]

def days_before(signal_date, top_date):
    return (top_date - signal_date).days

TOPS = [
    ("2013 top", "2013-01-01", "2014-06-01"),
    ("2017 top", "2017-01-01", "2018-06-01"),
    ("2021 top", "2021-01-01", "2022-06-01"),
]

for label, lo, hi in TOPS:
    win = btc.loc[lo:hi]
    top_date = win.idxmax()
    top_px = win.max()
    print(f"\n=== {label}: BTC ATH {top_date.date()} (${top_px:,.0f}) ===")

    # 1. Current engine exit: first day price < 200MA after top
    after = btc.loc[top_date:]
    cross = after[after < ma200[after.index]]
    if len(cross):
        d = cross.index[0]
        px_at_exit = btc.loc[d]
        dd_at_exit = (px_at_exit / top_px - 1) * 100
        print(f"  current engine exit (BTC<200MA): {d.date()}  {days_before(d, top_date):+d} days vs top  (already down {dd_at_exit:.0f}%)")

    # 2. M2 YoY peak (liquidity rollover)
    myoy = m2_yoy.loc[lo:hi].dropna()
    if len(myoy):
        pk = myoy.idxmax()
        rel = days_before(pk, top_date)
        print(f"  M2 YoY peak:                 {pk.date()}  {rel:+d} days vs top  (peak {myoy.max()*100:.1f}%)")

    # 3. Curve inversion (10y-3m negative)
    sp = spread.loc[lo:hi].dropna()
    inv = sp[sp < 0]
    if len(inv):
        d = inv.index[0]
        print(f"  curve inversion (10y-3m<0):  {d.date()}  {days_before(d, top_date):+d} days vs top")

    # 4. Stablecoin peak
    sw = stab.loc[lo:hi]
    if len(sw):
        pk = sw.idxmax()
        rel = days_before(pk, top_date)
        print(f"  stablecoin peak:             {pk.date()}  {rel:+d} days vs top")

    # 5. DXY reclaim of 200MA (dollar strength = risk-off)
    dx = dxy.loc[lo:hi]
    dm = dxy_ma[dx.index]
    up = dx[dx > dm]
    if len(up):
        d = up.index[0]
        print(f"  DXY reclaim 200MA:           {d.date()}  {days_before(d, top_date):+d} days vs top")

    # 6. F&G capitulation (<= 30)
    fw = fng.loc[lo:hi]
    if len(fw):
        fear = fw[fw <= 30]
        if len(fear):
            d = fear.index[0]
            print(f"  F&G <= 30 (fear):            {d.date()}  {days_before(d, top_date):+d} days vs top")
        else:
            print(f"  F&G <= 30:                   never in window")
    else:
        print(f"  F&G <= 30:                   no data before {lo}")
