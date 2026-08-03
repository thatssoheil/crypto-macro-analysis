#!/usr/bin/env python3
"""Diagnose walk-forward empty windows."""
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

pnl = session_momentum(df, 12, 23, 7, 0.4, 1.5, 1.0)
print(f"pnl index range: {pnl.index.min()} -> {pnl.index.max()}  n={len(pnl)}")
cur = pnl.index[0]
print(f"cur start: {cur}")
train_end = cur + pd.DateOffset(years=3)
print(f"train_end: {train_end}")
test_end = train_end + pd.DateOffset(years=1)
print(f"test_end: {test_end}")
print(f"test_end > pnl.index[-1]? {test_end > pnl.index[-1]}")
print(f"pnl last: {pnl.index[-1]}")
test = pnl[(pnl.index >= train_end) & (pnl.index < test_end)]
print(f"test len: {len(test)}")
