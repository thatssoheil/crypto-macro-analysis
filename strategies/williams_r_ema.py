#!/usr/bin/env python3
"""
Williams %R Mean Reversion with EMA Trend Filter (Kaufman)
Type: Mean reversion with trend confirmation
Win rate: 55-65% historically
"""
import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

DATA = Path(__file__).parent.parent / "data"

def load(pair):
    for suffix in ['', '_H1', '_YF', '_D1']:
        for folder in [DATA]:
            p = folder / f'{pair}{suffix}.csv'
            if p.exists():
                df = pd.read_csv(p, index_col=0, parse_dates=True)
                df.index = pd.to_datetime(df.index, utc=True)
                if len(df) > 500:
                    return df[['Open','High','Low','Close']].dropna()
    return None

def williams_r(high, low, close, period=10):
    hh = high.rolling(period).max()
    ll = low.rolling(period).min()
    return -100 * (hh - close) / (hh - ll)

def strat_williams_r_ema(df, wr_period=10, wr_ob=10, wr_os=90, 
                          ema_period=50, rr=2.0, session_filter=True):
    """
    Williams %R Reversal with EMA Trend Filter
    
    LONG: %R < oversold (90) AND price > EMA (uptrend)
    SHORT: %R > overbought (10) AND price < EMA (downtrend)
    TP: RR * SL distance
    SL: swing low/high
    """
    close = df['Close']
    high = df['High']
    low = df['Low']
    
    wr = williams_r(high, low, close, wr_period)
    ema = close.ewm(span=ema_period).mean()
    
    hour = pd.Series(df.index.hour, index=df.index) if hasattr(df.index, 'hour') else None
    
    trades = []
    position = 0
    entry_price = 0; sl_price = 0; tp_price = 0; entry_dir = 0
    
    for i in range(max(wr_period, ema_period) + 5, len(df)):
        if position == 0:
            # Long: oversold + uptrend
            if wr.iloc[i] < wr_os and close.iloc[i] > ema.iloc[i]:
                position = 1
                entry_price = close.iloc[i]
                # SL: recent swing low
                sl_price = low.iloc[max(0,i-10):i].min()
                sl_dist = entry_price - sl_price
                if sl_dist <= 0:
                    position = 0; continue
                tp_price = entry_price + sl_dist * rr
                entry_dir = 1
            # Short: overbought + downtrend
            elif wr.iloc[i] > wr_ob and close.iloc[i] < ema.iloc[i]:
                position = -1
                entry_price = close.iloc[i]
                sl_price = high.iloc[max(0,i-10):i].max()
                sl_dist = sl_price - entry_price
                if sl_dist <= 0:
                    position = 0; continue
                tp_price = entry_price - sl_dist * rr
                entry_dir = -1
        
        elif position != 0:
            exit_reason = None
            exit_price = close.iloc[i]
            
            if position == 1:
                if low.iloc[i] <= sl_price:
                    exit_price = sl_price; exit_reason = 'SL'
                elif high.iloc[i] >= tp_price:
                    exit_price = tp_price; exit_reason = 'TP'
                # Mean reversion exit: %R crosses back above exit level
                elif wr.iloc[i] > (100 - wr_os):
                    exit_reason = 'MR'
            elif position == -1:
                if high.iloc[i] >= sl_price:
                    exit_price = sl_price; exit_reason = 'SL'
                elif low.iloc[i] <= tp_price:
                    exit_price = tp_price; exit_reason = 'TP'
                elif wr.iloc[i] < (100 - wr_ob):
                    exit_reason = 'MR'
            
            if exit_reason:
                pnl = (exit_price - entry_price) / entry_price * entry_dir
                trades.append({
                    'date': df.index[i], 'pnl_pct': pnl, 'dir': entry_dir,
                    'reason': exit_reason, 'entry': entry_price, 'exit': exit_price
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
        print(f'  {label}: insufficient ({len(pnl)} bars)')
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
    reasons = pd.Series([t['reason'] for t in trades]).value_counts()
    
    print(f'  {label}')
    print(f'    Sh={sh:+.2f}  CAGR={cagr:+.1f}%  DD={dd:.1f}%  MedMo={med_mo:.2f}%  WinMo={win_mo:.0f}%')
    print(f'    N={n}  WR={wr:.0f}%  AvgW={avg_win*100:.3f}%  AvgL={avg_loss*100:.3f}%  RR={abs(avg_win/avg_loss):.1f}')
    print(f'    Exits: TP={reasons.get("TP",0)} SL={reasons.get("SL",0)} MR={reasons.get("MR",0)}')
    print(f'    WorstDay={worst_day:.2f}%  BestMo={monthly.max():.2f}%  WorstMo={monthly.min():.2f}%')
    print()

# ═══ TEST ═══
print('='*70)
print('WILLIAMS %R + EMA TREND FILTER (Kaufman)')
print('='*70)

for pair in ['EURUSD', 'GBPUSD', 'USDJPY']:
    df = load(pair)
    if df is None:
        continue
    print(f'\n--- {pair} ({len(df)} bars, {df.index[0].date()} -> {df.index[-1].date()}) ---')
    
    # Parameter sweep
    for wr_os in [85, 90, 95]:
        for ema_p in [20, 50, 100]:
            for rr in [1.5, 2.0, 3.0]:
                pnl, trades = strat_williams_r_ema(df, wr_os=wr_os, wr_ob=100-wr_os,
                                                     ema_period=ema_p, rr=rr)
                if len(pnl) > 30:
                    sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
                    if sh > 0.3:
                        n = len(trades)
                        monthly = pnl.resample('ME').sum() * 100
                        dd = ((1+pnl).cumprod() / (1+pnl).cumprod().cummax() - 1).min() * 100
                        print(f'  WR({wr_os}/{100-wr_os}) EMA={ema_p} RR={rr}  Sh={sh:+.2f}  DD={dd:.1f}%  MedMo={monthly.median():.2f}%  N={n}')
    
    # Best detail
    print(f'\n  --- Best detail ---')
    pnl, trades = strat_williams_r_ema(df, wr_os=90, wr_ob=10, ema_period=50, rr=2.0)
    stats(pnl, trades, f'{pair} WR(90/10) EMA50 RR2.0')
