#!/usr/bin/env python3
"""USDJPY Asian session re-validation on 10yr Dukascopy data."""
import pandas as pd, numpy as np
from pathlib import Path
import warnings, collections; warnings.filterwarnings('ignore')

DATA = Path("data")
df = pd.read_csv(DATA/'USDJPY_H1_DUKA.csv', index_col=0, parse_dates=True)
df.index = pd.to_datetime(df.index, utc=True)
df = df[['Open','High','Low','Close']].dropna()
print(f"Loaded: {len(df)} bars  {df.index[0].date()} -> {df.index[-1].date()}")

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

def show(pnl, label):
    if len(pnl) < 30:
        print(f"  {label}: insufficient data ({len(pnl)} days)"); return
    cum = (1 + pnl).cumprod()
    sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
    cagr = ((cum.iloc[-1])**(252/len(pnl)) - 1) * 100
    dd = (cum / cum.cummax() - 1).min() * 100
    monthly = pnl.resample('ME').sum() * 100
    print(f"  {label}")
    print(f"    Sh={sh:+.2f}  CAGR={cagr:+.1f}%  DD={dd:.1f}%  MedMo={monthly.median():.2f}%  WinMo={(monthly>0).mean()*100:.0f}%")
    print(f"    WorstDay={pnl.min()*100:.2f}%  BestMo={monthly.max():.2f}%  WorstMo={monthly.min():.2f}%")

print("\n=== USDJPY ASIAN SESSION ON 10yr DUKASCOPY ===")
for open_h, close_h, name in [(0,8,'Asian 00-08'), (1,9,'Asian 01-09'), (23,7,'Asian 23-07')]:
    pnl, trades = session_momentum(df, 8, open_h, close_h, 0.3, 1.5, 1.0)
    show(pnl, f"USDJPY {name} (risk=1%)")
    if len(trades) >= 30:
        reasons = collections.Counter(t['reason'] for t in trades)
        print(f"    trades={len(trades)}  SL={reasons['SL']} TP={reasons['TP']} EOD={reasons['EOD']}")

print("\n=== Walk-forward (3yr train/1yr test) ===")
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

for open_h, close_h, name in [(0,8,'Asian 00-08'), (1,9,'Asian 01-09')]:
    pnl, _ = session_momentum(df, 8, open_h, close_h, 0.3, 1.5, 1.0)
    wf = walk_forward(pnl)
    pos = sum(1 for w in wf if w['sh'] > 0)
    sh_str = '/'.join(f"{w['sh']:+.2f}" for w in wf)
    print(f"  {name}: {sh_str}  positive {pos}/{len(wf)}")
