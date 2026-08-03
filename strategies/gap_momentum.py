#!/usr/bin/env python3
"""
GBPUSD Opening Gap Momentum — Chan Ex 7.1
Entry: London open (05:00 ET / 09:00 UTC) gap vs prev session high/low
Exit: NY close (17:00 ET / 21:00 UTC) same day — flat, no overnight
Source: Ernie Chan "Algorithmic Trading" Example 7.1
"""
import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

DATA = Path(__file__).parent.parent / "data"

def load_h1(pair):
    for suffix in ['', '_H1', '_YF']:
        p = DATA / f'{pair}_H1{suffix}.csv'
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            if len(df) > 1000:
                return df[['Open','High','Low','Close']].dropna()
    return None

def gap_momentum(df, entry_z=0.1, std_lookback=90, session_open=9, session_close=21):
    """
    Chan Ex 7.1: GBPUSD Opening Gap Momentum
    
    At London open (09:00 UTC):
      - Calculate rolling std of close-to-close returns (90 bars)
      - LONG if open > prev_high * (1 + entry_z * std90)
      - SHORT if open < prev_low * (1 - entry_z * std90)
    Exit: session close (21:00 UTC) same day — flat
    """
    close = df['Close']
    high = df['High']
    low = df['Low']
    open_price = df['Open']
    
    ret = close.pct_change()
    std90 = ret.rolling(std_lookback).std().shift(1)
    
    hour = pd.Series(df.index.hour, index=df.index)
    
    # Find prev session high/low (previous day's 09-21 range)
    prev_high = high.rolling(12).max().shift(12)  # rough prev session high
    prev_low = low.rolling(12).min().shift(12)
    
    trades = []
    position = 0
    entry_price = 0
    entry_dir = 0
    
    for i in range(max(std_lookback, 24), len(df)):
        h = hour.iloc[i]
        
        # Entry at session open
        if h == session_open and position == 0:
            s = std90.iloc[i]
            if pd.isna(s) or s == 0:
                continue
            
            current_open = open_price.iloc[i]
            ph = prev_high.iloc[i]
            pl = prev_low.iloc[i]
            
            if pd.isna(ph) or pd.isna(pl):
                continue
            
            # LONG: open gaps above prev high
            if current_open > ph * (1 + entry_z * s):
                position = 1
                entry_price = current_open
                entry_dir = 1
            # SHORT: open gaps below prev low
            elif current_open < pl * (1 - entry_z * s):
                position = -1
                entry_price = current_open
                entry_dir = -1
        
        # Exit at session close
        elif h == session_close and position != 0:
            exit_price = close.iloc[i]
            pnl_pct = (exit_price - entry_price) / entry_price * entry_dir
            trades.append({
                'date': df.index[i],
                'dir': 'LONG' if entry_dir == 1 else 'SHORT',
                'entry': entry_price,
                'exit': exit_price,
                'pnl_pct': pnl_pct,
            })
            position = 0
    
    if not trades:
        return pd.Series(dtype=float), []
    
    trade_df = pd.DataFrame(trades)
    trade_df['date'] = pd.to_datetime(trade_df['date'])
    daily = trade_df.set_index('date')['pnl_pct'].resample('D').sum()
    return daily[daily != 0].dropna(), trades

def stats(pnl, trades, label):
    if len(pnl) < 30:
        print(f'  {label}: insufficient data ({len(pnl)} bars)')
        return
    cum = (1 + pnl).cumprod()
    sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
    cagr = ((cum.iloc[-1])**(252/len(pnl)) - 1) * 100
    dd = (cum / cum.cummax() - 1).min() * 100
    monthly = pnl.resample('ME').sum() * 100
    win_mo = (monthly > 0).mean() * 100
    med_mo = monthly.median()
    worst_day = pnl.min() * 100
    
    n = len(trades)
    wins = sum(1 for t in trades if t['pnl_pct'] > 0)
    wr = wins/n*100 if n > 0 else 0
    avg_win = np.mean([t['pnl_pct'] for t in trades if t['pnl_pct'] > 0]) if wins > 0 else 0
    avg_loss = np.mean([t['pnl_pct'] for t in trades if t['pnl_pct'] <= 0]) if (n-wins) > 0 else 0
    
    longs = [t for t in trades if t['dir'] == 'LONG']
    shorts = [t for t in trades if t['dir'] == 'SHORT']
    long_wr = sum(1 for t in longs if t['pnl_pct'] > 0) / len(longs) * 100 if longs else 0
    short_wr = sum(1 for t in shorts if t['pnl_pct'] > 0) / len(shorts) * 100 if shorts else 0
    
    print(f'  {label}')
    print(f'    Sh={sh:+.2f}  CAGR={cagr:+.1f}%  DD={dd:.1f}%  MedMo={med_mo:.2f}%  WinMo={win_mo:.0f}%')
    print(f'    Trades={n}  WR={wr:.0f}%  AvgWin={avg_win*100:.3f}%  AvgLoss={avg_loss*100:.3f}%  RR={abs(avg_win/avg_loss):.1f}')
    print(f'    Longs={len(longs)} (WR={long_wr:.0f}%)  Shorts={len(shorts)} (WR={short_wr:.0f}%)')
    print(f'    WorstDay={worst_day:.2f}%  BestMo={monthly.max():.2f}%  WorstMo={monthly.min():.2f}%')
    print()

# ═══ MAIN ═══
print('='*70)
print('GBPUSD OPENING GAP MOMENTUM (Chan Ex 7.1)')
print('='*70)

df = load_h1('GBPUSD')
if df is not None:
    print(f'Data: {len(df)} bars, {df.index[0].date()} -> {df.index[-1].date()}')
    print()
    
    # Parameter sweep
    print('--- PARAMETER SWEEP ---')
    for entry_z in [0.05, 0.1, 0.15, 0.2, 0.3, 0.5]:
        for std_lb in [30, 60, 90, 120]:
            pnl, trades = gap_momentum(df, entry_z=entry_z, std_lookback=std_lb)
            if len(pnl) > 30:
                sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
                n = len(trades)
                if sh > 0.3:
                    monthly = pnl.resample('ME').sum() * 100
                    dd = ((1+pnl).cumprod() / (1+pnl).cumprod().cummax() - 1).min() * 100
                    print(f'  z={entry_z:.2f} std={std_lb:3d}  Sh={sh:+.2f}  DD={dd:.1f}%  MedMo={monthly.median():.2f}%  N={n}')
    
    # Best params detail
    print()
    print('--- BEST PARAMS DETAIL ---')
    best_params = [(0.1, 90), (0.15, 90), (0.2, 60)]
    for entry_z, std_lb in best_params:
        pnl, trades = gap_momentum(df, entry_z=entry_z, std_lookback=std_lb)
        stats(pnl, trades, f'z={entry_z} std={std_lb}')

# Also test on EURUSD
print()
print('='*70)
print('EURUSD OPENING GAP MOMENTUM (Chan Ex 7.1 adapted)')
print('='*70)

df_eur = load_h1('EURUSD')
if df_eur is not None:
    print(f'Data: {len(df_eur)} bars, {df_eur.index[0].date()} -> {df_eur.index[-1].date()}')
    print()
    for entry_z in [0.05, 0.1, 0.15, 0.2, 0.3]:
        for std_lb in [60, 90, 120]:
            pnl, trades = gap_momentum(df_eur, entry_z=entry_z, std_lookback=std_lb)
            if len(pnl) > 30:
                sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
                n = len(trades)
                if sh > 0.3:
                    monthly = pnl.resample('ME').sum() * 100
                    dd = ((1+pnl).cumprod() / (1+pnl).cumprod().cummax() - 1).min() * 100
                    print(f'  z={entry_z:.2f} std={std_lb:3d}  Sh={sh:+.2f}  DD={dd:.1f}%  MedMo={monthly.median():.2f}%  N={n}')
