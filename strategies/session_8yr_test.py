#!/usr/bin/env python3
"""Session momentum backtest on 8yr MT5 data with walk-forward."""
import pandas as pd, numpy as np
from pathlib import Path
import warnings; warnings.filterwarnings('ignore')

DATA = Path(__file__).parent.parent / "data"

def load(pair):
    for p in [DATA / f'{pair}_H1_DUKA.csv', DATA / f'{pair}_H1_MT5.csv', DATA / f'{pair}_H1.csv', DATA / f'{pair}_cash_H1.csv']:
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            if len(df) > 1000: return df[['Open','High','Low','Close']].dropna()
    return None

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
    if len(pnl) < 30: return
    cum = (1 + pnl).cumprod()
    sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
    cagr = ((cum.iloc[-1])**(252/len(pnl)) - 1) * 100
    dd = (cum / cum.cummax() - 1).min() * 100
    monthly = pnl.resample('ME').sum() * 100
    print(f'  {label}')
    print(f'    Sh={sh:+.2f}  CAGR={cagr:+.1f}%  DD={dd:.1f}%  MedMo={monthly.median():.2f}%  WinMo={(monthly>0).mean()*100:.0f}%')
    print(f'    WorstDay={pnl.min()*100:.2f}%  BestMo={monthly.max():.2f}%  WorstMo={monthly.min():.2f}%')

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

print('='*70)
print('SESSION MOMENTUM ON 8yr MT5 DATA')
print('='*70)

# EURUSD
df = load('EURUSD')
print(f'\nEURUSD ({len(df)} bars, {df.index[0].date()} -> {df.index[-1].date()})')
eur_075, eur_t075 = session_momentum(df, 8, 7, 21, 0.3, 1.5, 0.75)
eur_100, eur_t100 = session_momentum(df, 8, 7, 21, 0.3, 1.5, 1.0)
show(eur_075, 'EURUSD London (risk=0.75%)')
show(eur_100, 'EURUSD London (risk=1.0%)')

wf = walk_forward(eur_100)
print('  Walk-forward (3yr train / 1yr test, risk=1.0%):')
pos = sum(1 for w in wf if w['sh'] > 0)
for w in wf:
    print(f"    {w['start']} -> {w['end']}: Sh={w['sh']:+.2f} {'PASS' if w['sh']>0.5 else 'FAIL'}")
print(f"  Positive: {pos}/{len(wf)} ({pos/max(len(wf),1)*100:.0f}%)")

# GBPUSD
df_gbp = load('GBPUSD')
print(f'\nGBPUSD ({len(df_gbp)} bars, {df_gbp.index[0].date()} -> {df_gbp.index[-1].date()})')
gbp_075, gbp_t = session_momentum(df_gbp, 8, 7, 21, 0.3, 1.5, 0.75)
show(gbp_075, 'GBPUSD London (risk=0.75%)')

# XAUUSD
df_xau = load('XAUUSD')
print(f'\nXAUUSD ({len(df_xau)} bars, {df_xau.index[0].date()} -> {df_xau.index[-1].date()})')
xau_075, xau_t = session_momentum(df_xau, 8, 7, 21, 0.3, 1.5, 0.75)
show(xau_075, 'XAUUSD London (risk=0.75%)')

# Combined portfolio
print('\n' + '='*70)
print('COMBINED SESSION PORTFOLIO')
print('='*70)
combined = pd.DataFrame({'EUR': eur_075, 'GBP': gbp_075, 'XAU': xau_075}).fillna(0)
combined = combined[(combined != 0).any(axis=1)]
port = combined['EUR'] + combined['GBP'] + combined['XAU']
show(port, 'EUR+GBP+XAU session (risk=0.75% each)')

corr = combined[combined.any(axis=1)].corr()
print(f'  Correlations: EUR/GBP={corr.loc["EUR","GBP"]:+.3f}  EUR/XAU={corr.loc["EUR","XAU"]:+.3f}  GBP/XAU={corr.loc["GBP","XAU"]:+.3f}')

wf_port = walk_forward(port)
print('\n  Walk-forward (combined):')
pos = sum(1 for w in wf_port if w['sh'] > 0)
for w in wf_port:
    print(f"    {w['start']} -> {w['end']}: Sh={w['sh']:+.2f} {'PASS' if w['sh']>0.5 else 'FAIL'}")
print(f"  Positive: {pos}/{len(wf_port)} ({pos/max(len(wf_port),1)*100:.0f}%)")
