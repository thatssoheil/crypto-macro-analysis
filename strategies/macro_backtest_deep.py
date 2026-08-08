#!/usr/bin/env python3
"""
MACRO BACKTEST - DEEP HISTORY (2011-2026)
Pure 200d-MA trend filter on Bitstamp BTCUSD daily from the local dataset.
No F&G dependency (F&G only starts 2018-05) -> we can test back to 2011.
Tests: what did the trend filter do in 2013-15 bear, 2018 bear, 2020 crash, 2022 bear?
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np



def load_btc():
    df = pd.read_csv(Path(__file__).parent.parent / "data" / "macro_dataset" / "btcusd_daily_bitstamp.csv")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()
    return df["close"]

def backtest(start, end, start_cash=10000):
    px = load_btc()
    px = px[(px.index >= start) & (px.index <= end)]
    if len(px) < 250: return None
    ma200 = px.rolling(200).mean()
    # Trend-follow: in market when price >= 200MA, cash when below
    in_market = pd.Series(True, index=px.index)
    valid = ma200.notna()
    in_market[valid] = px[valid] >= ma200[valid]
    rets = px.pct_change().fillna(0)
    eq_tf = (1 + rets * in_market).cumprod() * start_cash
    eq_bh = (1 + rets).cumprod() * start_cash
    dd_tf = (eq_tf / eq_tf.cummax() - 1).min() * 100
    dd_bh = (eq_bh / eq_bh.cummax() - 1).min() * 100
    # Cash periods
    cash_days = int((~in_market).sum())
    return {
        "start": str(px.index[0].date()), "end": str(px.index[-1].date()),
        "days": len(px), "cash_days": cash_days,
        "tf_final": float(eq_tf.iloc[-1]), "bh_final": float(eq_bh.iloc[-1]),
        "tf_pct": float((eq_tf.iloc[-1]/start_cash-1)*100),
        "bh_pct": float((eq_bh.iloc[-1]/start_cash-1)*100),
        "dd_tf": float(dd_tf), "dd_bh": float(dd_bh),
        "tf_per_yr": float(((eq_tf.iloc[-1]/start_cash)**(365/len(px))-1)*100),
        "bh_per_yr": float(((eq_bh.iloc[-1]/start_cash)**(365/len(px))-1)*100),
    }

print("=== 200d-MA TREND FILTER - DEEP HISTORY BACKTEST (Bitstamp, local data) ===\n")
for label, s, e in [
    ("FULL (2011-2026)", "2011-08-18", "2026-08-03"),
    ("Pre-2017 (2011-2017)", "2011-08-18", "2016-12-31"),
    ("2013-15 bear included", "2013-01-01", "2015-12-31"),
    ("2017-2026 (validated)", "2017-01-01", "2026-08-03"),
    ("2020 crash test", "2019-01-01", "2021-12-31"),
    ("2022 bear test", "2021-01-01", "2023-12-31"),
]:
    r = backtest(s, e)
    if not r:
        print(f"{label}: insufficient data"); continue
    print(f"\n{label}  ({r['start']} -> {r['end']}, {r['days']} days, {r['cash_days']} cash days)")
    print(f"  Trend-follow: ${r['tf_final']:>12,.0f}  ({r['tf_pct']:>+9.0f}%)  DD {r['dd_tf']:>5.1f}%  {r['tf_per_yr']:>+6.1f}%/yr")
    print(f"  Buy-hold:     ${r['bh_final']:>12,.0f}  ({r['bh_pct']:>+9.0f}%)  DD {r['dd_bh']:>5.1f}%  {r['bh_per_yr']:>+6.1f}%/yr")

# Stateless: per-window results printed above; nothing persisted.
