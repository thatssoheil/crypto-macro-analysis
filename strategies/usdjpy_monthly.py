#!/usr/bin/env python3
"""Monthly return analysis for USDJPY Asian 23-07 on 10yr Dukascopy."""
import pandas as pd, numpy as np
from pathlib import Path
import warnings; warnings.filterwarnings('ignore')

DATA = Path("data")
df = pd.read_csv(DATA/'USDJPY_H1_DUKA.csv', index_col=0, parse_dates=True)
df.index = pd.to_datetime(df.index, utc=True)
df = df[['Open','High','Low','Close']].dropna()

def session_momentum(df, pre_hours, session_open, session_close, atr_mult, rr, risk_pct, atr_period=14):
    close = df['Close'].values; high_arr = df['High'].values; low_arr = df['Low'].values
    hour = pd.Series(df.index.hour, index=df.index)
    tr = np.maximum(high_arr - low_arr, np.maximum(np.abs(high_arr - np.roll(close, 1)), np.abs(low_arr - np.roll(close, 1))))
    atr = pd.Series(tr).rolling(atr_period).mean().values
    equity = 100000.0; daily_equity = {}; position = 0
    for i in range(atr_period + pre_hours, len(df)):
        h = hour.iloc[i]; day = df.index[i].date()
        if position == 0 and h == session_open:
            pre_high = np.max(high_arr[i-pre_hours:i]); pre_low = np.min(low_arr[i-pre_hours:i])
            if (pre_high - pre_low) < atr[i] * 0.3: continue
            buffer = atr[i] * atr_mult; entry_price = close[i]
            if close[i] > pre_high + buffer:
                position = 1; sl_price = pre_low - buffer; sl_dist = entry_price - sl_price
                tp_price = entry_price + sl_dist * rr; position_size = (equity * risk_pct / 100) / sl_dist
            elif close[i] < pre_low - buffer:
                position = -1; sl_price = pre_high + buffer; sl_dist = sl_price - entry_price
                tp_price = entry_price - sl_dist * rr; position_size = (equity * risk_pct / 100) / sl_dist
        elif position != 0:
            exit_price = close[i]; exit_reason = None
            if position == 1:
                if low_arr[i] <= sl_price: exit_price = sl_price; exit_reason = 'SL'
                elif high_arr[i] >= tp_price: exit_price = tp_price; exit_reason = 'TP'
                elif h == session_close: exit_reason = 'EOD'
            elif position == -1:
                if high_arr[i] >= sl_price: exit_price = sl_price; exit_reason = 'SL'
                elif low_arr[i] <= tp_price: exit_price = tp_price; exit_reason = 'TP'
                elif h == session_close: exit_reason = 'EOD'
            if exit_reason:
                pnl = (exit_price - entry_price) * position * position_size; equity += pnl
                daily_equity[day] = daily_equity.get(day, 0) + pnl / equity
                position = 0
    if not daily_equity: return pd.Series(dtype=float)
    s = pd.Series(daily_equity); s.index = pd.to_datetime(s.index, utc=True); return s

print("=== USDJPY Asian 23-07 (live config: atr_mult 0.3, rr 2.0) ===")
for risk in [1.0, 2.0, 3.0, 4.0]:
    pnl = session_momentum(df, 4, 23, 7, 0.3, 2.0, risk)
    monthly = pnl.resample('ME').sum() * 100  # %
    cum = (1 + pnl).cumprod()
    total = (cum.iloc[-1] - 1) * 100
    years = (pnl.index[-1] - pnl.index[0]).days / 365.25
    cagr = ((cum.iloc[-1])**(1/years) - 1) * 100
    dd = (cum / cum.cummax() - 1).min() * 100
    sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
    print(f"\n  risk={risk}%:")
    print(f"    total {total:+.1f}% over {years:.1f}yr  CAGR {cagr:+.1f}%/yr")
    print(f"    monthly: mean {monthly.mean():+.2f}%  median {monthly.median():+.2f}%  win {(monthly>0).mean()*100:.0f}%")
    print(f"    best {monthly.max():+.2f}%  worst {monthly.min():+.2f}%  std {monthly.std():.2f}%")
    print(f"    Sharpe {sh:+.2f}  maxDD {dd:.1f}%")

# Monthly return distribution at live risk (1%)
print("\n=== Monthly return distribution (risk=1%, rr=2.0) ===")
pnl = session_momentum(df, 4, 23, 7, 0.3, 2.0, 1.0)
monthly = pnl.resample('ME').sum() * 100
print(f"  months: {len(monthly)}  positive: {(monthly>0).sum()}  negative: {(monthly<=0).sum()}")
print(f"  mean: {monthly.mean():+.2f}%  median: {monthly.median():+.2f}%")
print(f"  p10: {monthly.quantile(0.1):+.2f}%  p25: {monthly.quantile(0.25):+.2f}%  p75: {monthly.quantile(0.75):+.2f}%  p90: {monthly.quantile(0.9):+.2f}%")
print("\n  recent 24 months:")
print(monthly.tail(24).to_string())

# recent vs early
early = monthly[monthly.index < '2023-01-01']
late = monthly[monthly.index >= '2023-01-01']
print(f"\n  Jan2016-Dec2022: mean {early.mean():+.2f}%/mo  win {(early>0).mean()*100:.0f}%")
print(f"  Jan2023-Jul2026: mean {late.mean():+.2f}%/mo  win {(late>0).mean()*100:.0f}%")
