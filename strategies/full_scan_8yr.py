#!/usr/bin/env python3
"""Comprehensive strategy scan on 8yr MT5 H1 data. Find 3-4 uncorrelated edges."""
import pandas as pd, numpy as np
from pathlib import Path
import warnings; warnings.filterwarnings('ignore')

DATA = Path(__file__).parent.parent / "data"

def load(pair):
    for p in [DATA / f'{pair}_H1_MT5.csv', DATA / f'{pair}_cash_H1.csv', DATA / f'{pair}_H1.csv']:
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            if len(df) > 1000: return df[['Open','High','Low','Close']].dropna()
    return None

def session_momentum(df, pre_hours, session_open, session_close, atr_mult, rr, risk_pct):
    close = df['Close'].values; high_arr = df['High'].values; low_arr = df['Low'].values
    hour = pd.Series(df.index.hour, index=df.index)
    tr = np.maximum(high_arr - low_arr, np.maximum(np.abs(high_arr - np.roll(close, 1)), np.abs(low_arr - np.roll(close, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    equity = 100000.0; daily_equity = {}; position = 0
    for i in range(14 + pre_hours, len(df)):
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
                daily_equity[day] = daily_equity.get(day, 0) + pnl / equity; position = 0
    if not daily_equity: return pd.Series(dtype=float)
    s = pd.Series(daily_equity); s.index = pd.to_datetime(s.index, utc=True); return s

def rsi_bb_momentum(df, rsi_period=14, bb_period=20, bb_std=2.0, ema_period=50, rr=2.0, risk_pct=0.5):
    """RSI + BB + EMA trend filter mean reversion on H1."""
    close_s = df['Close']; high_s = df['High']; low_s = df['Low']
    close = close_s.values; high = high_s.values; low = low_s.values
    
    delta = close_s.diff()
    gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).values
    
    sma = close_s.rolling(bb_period).mean().values
    std = close_s.rolling(bb_period).std().values
    ema = close_s.ewm(span=ema_period).mean().values
    
    equity = 100000.0; daily_equity = {}; position = 0
    for i in range(max(rsi_period, bb_period, ema_period) + 5, len(df)):
        day = df.index[i].date()
        if position == 0:
            # Long: RSI oversold + price at lower BB + uptrend
            if rsi[i] < 30 and close[i] < sma[i] - bb_std * std[i] and close[i] > ema[i]:
                position = 1; entry_price = close[i]
                sl_price = low[i-10:i].min(); sl_dist = entry_price - sl_price
                if sl_dist > 0:
                    tp_price = entry_price + sl_dist * rr
                    position_size = (equity * risk_pct / 100) / sl_dist
                else: position = 0
            # Short: RSI overbought + price at upper BB + downtrend
            elif rsi[i] > 70 and close[i] > sma[i] + bb_std * std[i] and close[i] < ema[i]:
                position = -1; entry_price = close[i]
                sl_price = high[i-10:i].max(); sl_dist = sl_price - entry_price
                if sl_dist > 0:
                    tp_price = entry_price - sl_dist * rr
                    position_size = (equity * risk_pct / 100) / sl_dist
                else: position = 0
        elif position != 0:
            exit_price = close[i]; exit_reason = None
            if position == 1:
                if low[i] <= sl_price: exit_price = sl_price; exit_reason = 'SL'
                elif high[i] >= tp_price: exit_price = tp_price; exit_reason = 'TP'
                elif rsi[i] > 70: exit_reason = 'MR'
            elif position == -1:
                if high[i] >= sl_price: exit_price = sl_price; exit_reason = 'SL'
                elif low[i] <= tp_price: exit_price = tp_price; exit_reason = 'TP'
                elif rsi[i] < 30: exit_reason = 'MR'
            if exit_reason:
                pnl = (exit_price - entry_price) * position * position_size; equity += pnl
                daily_equity[day] = daily_equity.get(day, 0) + pnl / equity; position = 0
    if not daily_equity: return pd.Series(dtype=float)
    s = pd.Series(daily_equity); s.index = pd.to_datetime(s.index, utc=True); return s

def donchian_breakout(df, lookback=55, rr=2.0, risk_pct=0.5):
    """N-day Donchian channel breakout on H1."""
    close_s = df['Close']; high_s = df['High']; low_s = df['Low']
    close = close_s.values; high = high_s.values; low = low_s.values
    
    equity = 100000.0; daily_equity = {}; position = 0
    for i in range(lookback + 5, len(df)):
        day = df.index[i].date()
        don_high = np.max(high[i-lookback:i])
        don_low = np.min(low[i-lookback:i])
        
        if position == 0:
            if close[i] > don_high:
                position = 1; entry_price = close[i]
                sl_price = don_low; sl_dist = entry_price - sl_price
                if sl_dist > 0:
                    tp_price = entry_price + sl_dist * rr
                    position_size = (equity * risk_pct / 100) / sl_dist
                else: position = 0
            elif close[i] < don_low:
                position = -1; entry_price = close[i]
                sl_price = don_high; sl_dist = sl_price - entry_price
                if sl_dist > 0:
                    tp_price = entry_price - sl_dist * rr
                    position_size = (equity * risk_pct / 100) / sl_dist
                else: position = 0
        elif position != 0:
            exit_price = close[i]; exit_reason = None
            if position == 1:
                if low[i] <= sl_price: exit_price = sl_price; exit_reason = 'SL'
                elif high[i] >= tp_price: exit_price = tp_price; exit_reason = 'TP'
            elif position == -1:
                if high[i] >= sl_price: exit_price = sl_price; exit_reason = 'SL'
                elif low[i] <= tp_price: exit_price = tp_price; exit_reason = 'TP'
            if exit_reason:
                pnl = (exit_price - entry_price) * position * position_size; equity += pnl
                daily_equity[day] = daily_equity.get(day, 0) + pnl / equity; position = 0
    if not daily_equity: return pd.Series(dtype=float)
    s = pd.Series(daily_equity); s.index = pd.to_datetime(s.index, utc=True); return s

def tsmom_d1(pair, risk_pct=0.5):
    """Time-series momentum on D1 data."""
    for p in [DATA / f'{pair}_D1.csv', DATA / f'{pair}_cash_D1.csv']:
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            close = df['Close'].dropna()
            break
    else:
        return pd.Series(dtype=float)
    
    returns = close.pct_change()
    vol = returns.ewm(span=36).std() * np.sqrt(252)
    signal = (np.sign(close.pct_change(63)) + np.sign(close.pct_change(126)) + np.sign(close.pct_change(252))) / 3
    weight = (0.15 / vol).replace([np.inf,-np.inf],0) * signal
    weight = weight.shift(1).clip(-5, 5)
    pnl = (weight * returns).dropna()
    return pnl

def show(pnl, label):
    if len(pnl) < 60: return None
    cum = (1 + pnl).cumprod()
    sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
    cagr = ((cum.iloc[-1])**(252/len(pnl)) - 1) * 100
    dd = (cum / cum.cummax() - 1).min() * 100
    monthly = pnl.resample('ME').sum() * 100
    med_mo = monthly.median(); win_mo = (monthly > 0).mean() * 100
    print(f'  {label:55s} Sh={sh:+.2f}  CAGR={cagr:+.1f}%  DD={dd:.1f}%  MedMo={med_mo:.2f}%  WinMo={win_mo:.0f}%')
    return sh

print('='*80)
print('COMPREHENSIVE STRATEGY SCAN — 8yr MT5 H1 data')
print('='*80)

results = {}

# ── SESSION MOMENTUM (London session, all pairs) ──
print('\n--- SESSION MOMENTUM (London 09-23 server = 07-21 UTC) ---')
# Server time: London open=09, close=23
for pair in ['EURUSD', 'GBPUSD', 'XAUUSD']:
    df = load(pair)
    if df is None: continue
    for pre_h in [6, 8, 10]:
        for rr in [1.5, 2.0, 3.0]:
            pnl = session_momentum(df, pre_h, 9, 23, 0.3, rr, 0.5)
            sh = show(pnl, f'{pair} pre={pre_h}h RR={rr} risk=0.5%')
            if sh and sh > 0.5:
                results[f'{pair}_London_pre{pre_h}_rr{rr}'] = pnl

# ── SESSION MOMENTUM (NY session) ──
print('\n--- SESSION MOMENTUM (NY session 15-22 server = 13-20 UTC) ---')
for pair in ['EURUSD', 'GBPUSD', 'XAUUSD']:
    df = load(pair)
    if df is None: continue
    for pre_h in [4, 6, 8]:
        for rr in [1.5, 2.0, 3.0]:
            pnl = session_momentum(df, pre_h, 15, 22, 0.3, rr, 0.5)
            sh = show(pnl, f'{pair} NY pre={pre_h}h RR={rr} risk=0.5%')
            if sh and sh > 0.5:
                results[f'{pair}_NY_pre{pre_h}_rr{rr}'] = pnl

# ── SESSION MOMENTUM (Asian session) ──
print('\n--- SESSION MOMENTUM (Asian 01-09 server = 23-07 UTC) ---')
for pair in ['EURUSD', 'GBPUSD', 'USDJPY']:
    df = load(pair)
    if df is None: continue
    for pre_h in [4, 6]:
        for rr in [1.5, 2.0]:
            pnl = session_momentum(df, pre_h, 1, 9, 0.3, rr, 0.5)
            sh = show(pnl, f'{pair} Asian pre={pre_h}h RR={rr} risk=0.5%')
            if sh and sh > 0.5:
                results[f'{pair}_Asian_pre{pre_h}_rr{rr}'] = pnl

# ── RSI + BB + EMA MEAN REVERSION ──
print('\n--- RSI + BB + EMA MEAN REVERSION ---')
for pair in ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY']:
    df = load(pair)
    if df is None: continue
    for ema_p in [20, 50, 100]:
        for rr in [1.5, 2.0, 3.0]:
            pnl = rsi_bb_momentum(df, ema_period=ema_p, rr=rr, risk_pct=0.5)
            sh = show(pnl, f'{pair} RSI+BB EMA={ema_p} RR={rr}')
            if sh and sh > 0.5:
                results[f'{pair}_RSIBB_ema{ema_p}_rr{rr}'] = pnl

# ── DONCHIAN BREAKOUT ──
print('\n--- DONCHIAN BREAKOUT ---')
for pair in ['EURUSD', 'GBPUSD', 'XAUUSD']:
    df = load(pair)
    if df is None: continue
    for lb in [20, 55, 100]:
        for rr in [1.5, 2.0, 3.0]:
            pnl = donchian_breakout(df, lookback=lb, rr=rr, risk_pct=0.5)
            sh = show(pnl, f'{pair} Donchian({lb}) RR={rr}')
            if sh and sh > 0.5:
                results[f'{pair}_Donchian_{lb}_rr{rr}'] = pnl

# ── D1 TSMOM ──
print('\n--- D1 TSMOM ---')
for pair in ['XAUUSD', 'US500', 'US100', 'EURUSD', 'GBPUSD']:
    pnl = tsmom_d1(pair, risk_pct=0.5)
    sh = show(pnl, f'{pair} TSMOM D1')
    if sh and sh > 0.3:
        results[f'{pair}_TSMOM_D1'] = pnl

# ── TOP STRATEGIES CORRELATION MATRIX ──
print('\n' + '='*80)
print(f'TOP STRATEGIES (Sharpe > 0.5): {len(results)} found')
print('='*80)

if len(results) >= 2:
    # Filter to top strategies
    top = {k: v for k, v in sorted(results.items(), key=lambda x: x[1].mean()/x[1].std() if x[1].std()>0 else 0, reverse=True)[:15]}
    
    # Align all to common dates
    all_pnl = pd.DataFrame(top).fillna(0)
    all_pnl = all_pnl[(all_pnl != 0).any(axis=1)]
    
    # Correlation matrix
    corr = all_pnl.corr()
    print('\nCorrelation matrix (top strategies):')
    for i, k1 in enumerate(list(top.keys())[:8]):
        corrs = []
        for k2 in list(top.keys())[:8]:
            corrs.append(f'{corr.loc[k1,k2]:+.2f}')
        print(f'  {k1[:25]:25s} {" ".join(corrs)}')
    
    # Find best uncorrelated combination
    print('\n--- BEST UNCORRELATED COMBINATIONS ---')
    strategy_names = list(top.keys())
    best_combo = None
    best_sh = 0
    
    for i in range(len(strategy_names)):
        for j in range(i+1, len(strategy_names)):
            c = corr.loc[strategy_names[i], strategy_names[j]]
            if abs(c) < 0.2:  # uncorrelated
                combo_pnl = (all_pnl[strategy_names[i]] + all_pnl[strategy_names[j]]) / 2
                sh = combo_pnl.mean() / combo_pnl.std() * np.sqrt(252) if combo_pnl.std() > 0 else 0
                if sh > best_sh:
                    best_sh = sh
                    best_combo = (strategy_names[i], strategy_names[j], c, sh)
    
    if best_combo:
        print(f'  Best pair: {best_combo[0]} + {best_combo[1]}')
        print(f'    Correlation: {best_combo[2]:+.3f}')
        print(f'    Combined Sharpe: {best_combo[3]:+.2f}')
        
        combo_pnl = (all_pnl[best_combo[0]] + all_pnl[best_combo[1]]) / 2
        cum = (1 + combo_pnl).cumprod()
        cagr = ((cum.iloc[-1])**(252/len(combo_pnl)) - 1) * 100
        dd = (cum / cum.cummax() - 1).min() * 100
        monthly = combo_pnl.resample('ME').sum() * 100
        print(f'    CAGR: {cagr:+.1f}%  DD: {dd:.1f}%  MedMo: {monthly.median():.2f}%')
    
    # Find best 3-strategy combo
    print('\n--- BEST 3-STRATEGY COMBO ---')
    from itertools import combinations
    for combo in combinations(strategy_names, 3):
        avg_corr = abs(corr.loc[combo[0], combo[1]]) + abs(corr.loc[combo[0], combo[2]]) + abs(corr.loc[combo[1], combo[2]])
        avg_corr /= 3
        if avg_corr < 0.15:  # all uncorrelated
            combo_pnl = sum(all_pnl[s] for s in combo) / 3
            sh = combo_pnl.mean() / combo_pnl.std() * np.sqrt(252) if combo_pnl.std() > 0 else 0
            if sh > best_sh * 0.9:  # within 90% of best pair
                cum = (1 + combo_pnl).cumprod()
                cagr = ((cum.iloc[-1])**(252/len(combo_pnl)) - 1) * 100
                dd = (cum / cum.cummax() - 1).min() * 100
                monthly = combo_pnl.resample('ME').sum() * 100
                print(f'  {combo[0][:20]} + {combo[1][:20]} + {combo[2][:20]}')
                print(f'    AvgCorr={avg_corr:.3f}  Sh={sh:+.2f}  CAGR={cagr:+.1f}%  DD={dd:.1f}%  MedMo={monthly.median():.2f}%')
