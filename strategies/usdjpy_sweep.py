#!/usr/bin/env python3
"""Full parameter sweep + walk-forward on USDJPY Asian (10yr Dukascopy)."""
import pandas as pd, numpy as np
from pathlib import Path
import warnings, itertools; warnings.filterwarnings('ignore')

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

def stats(pnl):
    if len(pnl) < 30: return None
    cum = (1 + pnl).cumprod()
    sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
    dd = (cum / cum.cummax() - 1).min() * 100
    monthly = pnl.resample('ME').sum() * 100
    return {'sh': sh, 'dd': dd, 'total': (cum.iloc[-1]-1)*100,
            'n': len(pnl), 'med_mo': monthly.median(), 'win_mo': (monthly>0).mean()*100,
            'worst_mo': monthly.min()}

def walk_forward(pnl, train_years=3, test_years=1):
    wins = []; cur = pnl.index[0]
    while cur < pnl.index[-1]:
        train_end = cur + pd.DateOffset(years=train_years)
        test_end = train_end + pd.DateOffset(years=test_years)
        if test_end > pnl.index[-1]: break
        test = pnl[(pnl.index >= train_end) & (pnl.index < test_end)]
        if len(test) >= 10:   # low-frequency strategy: 1yr test ~10-15 trades
            sh = test.mean() / test.std() * np.sqrt(252) if test.std() > 0 else 0
            wins.append(sh)
        cur = train_end
    return wins

# Full sweep
results = []
for pre in [6, 7, 8, 9, 10, 11, 12]:
    for atr_mult in [0.3, 0.4, 0.5]:
        for rr in [1.0, 1.5, 2.0]:
            pnl = session_momentum(df, pre, 23, 7, atr_mult, rr, 1.0)
            s = stats(pnl)
            if not s: continue
            wf = walk_forward(pnl)
            s.update({'pre': pre, 'atr': atr_mult, 'rr': rr,
                      'wf_pos': sum(1 for w in wf if w > 0), 'wf_n': len(wf),
                      'wf_mean': np.mean(wf) if wf else 0})
            results.append(s)

res = pd.DataFrame(results)
print("=== TOP 15 BY WALK-FORWARD (robustness-weighted) ===")
# rank: prefer wf_pos fraction high, then sharpe
res['wf_frac'] = res['wf_pos'] / res['wf_n'].clip(lower=1)
res['score'] = res['sh'] * 0.5 + res['wf_frac'] * 1.5
res = res.sort_values('score', ascending=False)
cols = ['pre','atr','rr','sh','dd','total','n','med_mo','win_mo','worst_mo','wf_pos','wf_n','wf_mean','score']
print(res[cols].head(15).to_string(index=False))

print("\n=== TOP 10 BY SHARPE (raw) ===")
print(res.sort_values('sh', ascending=False)[cols].head(10).to_string(index=False))

print("\n=== LIVE CONFIG CHECK (pre=4) ===")
s = stats(session_momentum(df, 4, 23, 7, 0.3, 2.0, 1.0))
print(f"  pre=4 atr=0.3 rr=2.0: Sh={s['sh']:+.2f} DD={s['dd']:.1f}% total={s['total']:+.1f}% n={s['n']}")
