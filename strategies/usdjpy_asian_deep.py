#!/usr/bin/env python3
"""Deep dive on USDJPY Asian 23-07 - the only config with real edge."""
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
    equity = 100000.0; daily_equity = {}; position = 0; trades = []
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
                trades.append({'pnl': pnl/equity, 'reason': exit_reason}); position = 0
    if not daily_equity: return pd.Series(dtype=float), []
    s = pd.Series(daily_equity); s.index = pd.to_datetime(s.index, utc=True); return s, trades

# Year-by-year breakdown for 23-07
pnl, trades = session_momentum(df, 8, 23, 7, 0.3, 1.5, 1.0)
print("=== USDJPY Asian 23-07: YEAR BY YEAR ===")
yearly = pnl.groupby(pnl.index.year).agg(['sum','count'])
for yr, row in yearly.iterrows():
    sh = row['sum']/row['count'] * np.sqrt(252) if row['count']>1 else 0
    print(f"  {yr}: ret={row['sum']*100:+6.2f}%  trades={int(row['count'])}  Sh={sh:+.2f}")
print(f"  TOTAL: {pnl.sum()*100:+.2f}%  n={len(pnl)}")

print("\n=== Walk-forward 3yr/1yr ===")
def walk_forward(pnl, train_years=3, test_years=1):
    windows = []; cur = pnl.index[0]
    while cur < pnl.index[-1]:
        train_end = cur + pd.DateOffset(years=train_years)
        test_end = train_end + pd.DateOffset(years=test_years)
        if test_end > pnl.index[-1]: break
        test = pnl[(pnl.index >= train_end) & (pnl.index < test_end)]
        if len(test) > 60:
            sh = test.mean() / test.std() * np.sqrt(252) if test.std() > 0 else 0
            windows.append({'start': str(train_end.date()), 'end': str(test_end.date()), 'sh': sh})
        cur = train_end
    return windows
wf = walk_forward(pnl)
pos = sum(1 for w in wf if w['sh'] > 0)
for w in wf:
    print(f"  {w['start']} -> {w['end']}: Sh={w['sh']:+.2f} {'PASS' if w['sh']>0.5 else 'FAIL'}")
print(f"  Positive: {pos}/{len(wf)}")

# Sensitivity: atr_mult and rr
print("\n=== Sensitivity (23-07) ===")
for atr_mult in [0.2, 0.3, 0.4, 0.5]:
    for rr in [1.0, 1.5, 2.0]:
        p, t = session_momentum(df, 8, 23, 7, atr_mult, rr, 1.0)
        if len(p) < 30: continue
        sh = p.mean()/p.std()*np.sqrt(252)
        dd = ((1+p).cumprod()/(1+p).cumprod().cummax()-1).min()*100
        print(f"  atr_mult={atr_mult} rr={rr}: Sh={sh:+.2f} DD={dd:.1f}% trades={len(t)}")
