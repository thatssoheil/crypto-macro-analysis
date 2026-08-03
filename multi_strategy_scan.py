#!/usr/bin/env python3
"""Multi-strategy scanner — find edges that can contribute 1-3%/month each."""
import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

DATA = Path('data')

def load_h1(name):
    """Load H1 data, try both Dukascopy and Yahoo sources."""
    for suffix in ['', '_H1', '_YF']:
        p = DATA / f'{name}_H1{suffix}.csv'
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            if len(df) > 1000:
                return df[['Open','High','Low','Close']].dropna()
    return None

def load_d1(name):
    p = DATA / f'{name}_D1.csv'
    if p.exists():
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        return df[['Open','High','Low','Close']].dropna()
    return None

def stats(pnl, label, prefix=''):
    if len(pnl) < 60:
        print(f'  {prefix}{label:50s} INSUFFICIENT DATA ({len(pnl)} bars)')
        return None
    cum = (1 + pnl).cumprod()
    sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
    cagr = ((cum.iloc[-1])**(252/len(pnl)) - 1) * 100
    dd = (cum / cum.cummax() - 1).min() * 100
    monthly = pnl.resample('ME').sum() * 100
    win_mo = (monthly > 0).mean() * 100
    med_mo = monthly.median()
    worst_day = pnl.min() * 100
    print(f'  {prefix}{label:50s} Sh={sh:+.2f}  CAGR={cagr:+.1f}%  DD={dd:.1f}%  '
          f'WinMo={win_mo:.0f}%  MedMo={med_mo:.2f}%  WorstDay={worst_day:.2f}%')
    return sh

# ═══════════════════════════════════════════════════════════════
# STRATEGY 1: INTRADAY MEAN REVERSION (RSI bounce in ranges)
# ═══════════════════════════════════════════════════════════════
def strat_mean_reversion(df, rsi_period=14, rsi_oversold=30, rsi_overbought=70,
                         bb_period=20, bb_std=2.0, rr=2.0, session_filter=True):
    """
    RSI + Bollinger Band mean reversion on H1.
    Buy when RSI < oversold AND price touches lower BB.
    Sell when RSI > overbought AND price touches upper BB.
    SL: opposite BB. TP: RR * SL distance.
    Session filter: only trade during London+NY (07:00-21:00 UTC).
    """
    close = df['Close']
    high = df['High']
    low = df['Low']
    
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    # Bollinger Bands
    sma = close.rolling(bb_period).mean()
    std = close.rolling(bb_period).std()
    upper_bb = sma + bb_std * std
    lower_bb = sma - bb_std * std
    
    # Session filter (London+NY: 07-21 UTC)
    if session_filter:
        hour = pd.Series(df.index.hour, index=df.index)
        in_session = (hour >= 7) & (hour <= 21)
    else:
        in_session = pd.Series(True, index=df.index)
    
    # Generate signals
    signals = pd.Series(0.0, index=df.index)
    entry_prices = pd.Series(np.nan, index=df.index)
    sl_prices = pd.Series(np.nan, index=df.index)
    tp_prices = pd.Series(np.nan, index=df.index)
    
    position = 0  # 0=flat, 1=long, -1=short
    entry_price = 0
    sl_price = 0
    tp_price = 0
    
    for i in range(bb_period, len(df)):
        if position == 0:
            # Long entry
            if (rsi.iloc[i] < rsi_oversold and 
                low.iloc[i] <= lower_bb.iloc[i] and 
                in_session.iloc[i]):
                position = 1
                entry_price = close.iloc[i]
                sl_price = lower_bb.iloc[i] - (upper_bb.iloc[i] - lower_bb.iloc[i]) * 0.5
                tp_price = entry_price + (entry_price - sl_price) * rr
                signals.iloc[i] = 1
            # Short entry
            elif (rsi.iloc[i] > rsi_overbought and 
                  high.iloc[i] >= upper_bb.iloc[i] and 
                  in_session.iloc[i]):
                position = -1
                entry_price = close.iloc[i]
                sl_price = upper_bb.iloc[i] + (upper_bb.iloc[i] - lower_bb.iloc[i]) * 0.5
                tp_price = entry_price - (sl_price - entry_price) * rr
                signals.iloc[i] = -1
        else:
            # Check exit
            if position == 1:
                if low.iloc[i] <= sl_price:
                    pnl = (sl_price - entry_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
                elif high.iloc[i] >= tp_price:
                    pnl = (tp_price - entry_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
                else:
                    signals.iloc[i] = 0  # hold
            elif position == -1:
                if high.iloc[i] >= sl_price:
                    pnl = (entry_price - sl_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
                elif low.iloc[i] <= tp_price:
                    pnl = (entry_price - tp_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
                else:
                    signals.iloc[i] = 0
    
    # Convert trade signals to equity curve
    # Only count non-zero signals as trade PnL
    trade_pnl = signals[signals != 0]
    # Filter out hold signals (0) and entry signals (1, -1)
    trade_pnl = trade_pnl[(trade_pnl != 1) & (trade_pnl != -1)]
    
    if len(trade_pnl) == 0:
        return pd.Series(dtype=float)
    
    # Create daily equity curve from trades
    trade_pnl.index = pd.to_datetime(trade_pnl.index)
    daily_pnl = trade_pnl.resample('D').sum()
    return daily_pnl[daily_pnl != 0].dropna()

# ═══════════════════════════════════════════════════════════════
# STRATEGY 2: SESSION MOMENTUM (London/NY open breakouts)
# ═══════════════════════════════════════════════════════════════
def strat_session_momentum(df, lookback=6, atr_period=14, atr_mult=1.0, rr=1.5):
    """
    Session breakout: at London open (07:00), if price breaks above/below
    the Asian session range (00:00-07:00), enter in that direction.
    SL: opposite end of range + buffer. TP: RR * SL.
    """
    close = df['Close']
    high = df['High']
    low = df['Low']
    
    # ATR for dynamic stops
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(atr_period).mean()
    
    signals = pd.Series(0.0, index=df.index)
    position = 0
    entry_price = 0
    sl_price = 0
    tp_price = 0
    
    for i in range(atr_period + lookback, len(df)):
        hour = df.index[i].hour
        
        # At London open (07:00), check Asian range breakout
        if hour == 7 and position == 0:
            # Asian range: last 7 hours (00:00-07:00)
            asian_high = high.iloc[i-lookback:i].max()
            asian_low = low.iloc[i-lookback:i].min()
            asian_range = asian_high - asian_low
            
            # Skip if range is too tight (consolidation)
            if asian_range < atr.iloc[i] * 0.5:
                continue
            
            current_close = close.iloc[i]
            buffer = atr.iloc[i] * atr_mult
            
            if current_close > asian_high + buffer:
                # Long breakout
                position = 1
                entry_price = current_close
                sl_price = asian_low - buffer
                tp_price = entry_price + (entry_price - sl_price) * rr
                signals.iloc[i] = 1
            elif current_close < asian_low - buffer:
                # Short breakout
                position = -1
                entry_price = current_close
                sl_price = asian_high + buffer
                tp_price = entry_price - (sl_price - entry_price) * rr
                signals.iloc[i] = -1
        
        # Check exits
        elif position != 0:
            if position == 1:
                if low.iloc[i] <= sl_price:
                    pnl = (sl_price - entry_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
                elif high.iloc[i] >= tp_price:
                    pnl = (tp_price - entry_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
            elif position == -1:
                if high.iloc[i] >= sl_price:
                    pnl = (entry_price - sl_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
                elif low.iloc[i] <= tp_price:
                    pnl = (entry_price - tp_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
    
    trade_pnl = signals[(signals != 0) & (signals != 1) & (signals != -1)]
    if len(trade_pnl) == 0:
        return pd.Series(dtype=float)
    trade_pnl.index = pd.to_datetime(trade_pnl.index)
    daily_pnl = trade_pnl.resample('D').sum()
    return daily_pnl[daily_pnl != 0].dropna()

# ═══════════════════════════════════════════════════════════════
# STRATEGY 3: VOLATILITY BREAKOUT (ATR compression → expansion)
# ═══════════════════════════════════════════════════════════════
def strat_vol_breakout(df, atr_period=14, squeeze_period=20, 
                       squeeze_threshold=0.7, rr=2.0):
    """
    When ATR compresses to below threshold of its rolling avg,
    then price breaks out of the compression range, enter.
    """
    close = df['Close']
    high = df['High']
    low = df['Low']
    
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(atr_period).mean()
    atr_avg = atr.rolling(squeeze_period).mean()
    
    # Squeeze: ATR below threshold of its average
    squeezed = atr < atr_avg * squeeze_threshold
    
    # Range during squeeze
    range_high = high.rolling(squeeze_period).max()
    range_low = low.rolling(squeeze_period).min()
    
    signals = pd.Series(0.0, index=df.index)
    position = 0
    entry_price = 0
    sl_price = 0
    tp_price = 0
    
    for i in range(squeeze_period * 2, len(df)):
        if position == 0:
            # Look for squeeze then breakout
            was_squeezed = squeezed.iloc[i-3:i].any()
            
            if was_squeezed:
                if close.iloc[i] > range_high.iloc[i-1]:
                    position = 1
                    entry_price = close.iloc[i]
                    sl_price = range_low.iloc[i-1]
                    tp_price = entry_price + (entry_price - sl_price) * rr
                    signals.iloc[i] = 1
                elif close.iloc[i] < range_low.iloc[i-1]:
                    position = -1
                    entry_price = close.iloc[i]
                    sl_price = range_high.iloc[i-1]
                    tp_price = entry_price - (sl_price - entry_price) * rr
                    signals.iloc[i] = -1
        
        elif position != 0:
            if position == 1:
                if low.iloc[i] <= sl_price:
                    pnl = (sl_price - entry_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
                elif high.iloc[i] >= tp_price:
                    pnl = (tp_price - entry_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
            elif position == -1:
                if high.iloc[i] >= sl_price:
                    pnl = (entry_price - sl_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
                elif low.iloc[i] <= tp_price:
                    pnl = (entry_price - tp_price) / entry_price
                    signals.iloc[i] = pnl
                    position = 0
    
    trade_pnl = signals[(signals != 0) & (signals != 1) & (signals != -1)]
    if len(trade_pnl) == 0:
        return pd.Series(dtype=float)
    trade_pnl.index = pd.to_datetime(trade_pnl.index)
    daily_pnl = trade_pnl.resample('D').sum()
    return daily_pnl[daily_pnl != 0].dropna()

# ═══════════════════════════════════════════════════════════════
# STRATEGY 4: CARRY TRADE (D1 — long high-yield, short low-yield)
# ═══════════════════════════════════════════════════════════════
def strat_carry_trade_d1(prices_dict, lookback=63):
    """
    Carry trade proxy: rank currencies by recent momentum (proxy for rate differential).
    Long top 2, short bottom 2. Rebalance monthly.
    Simplified: just long AUD/JPY (high carry), short EUR/CHF (low carry).
    """
    # Use available pairs to construct carry proxy
    # AUDUSD = high carry, USDJPY = short JPY = long carry
    # EURUSD = medium, GBPUSD = medium
    
    available = list(prices_dict.keys())
    if len(available) < 2:
        return pd.Series(dtype=float)
    
    # Simple carry proxy: long highest momentum pair, short lowest
    returns = pd.DataFrame(prices_dict).pct_change()
    mom = pd.DataFrame(prices_dict).pct_change(lookback)
    
    # Equal weight long top half, short bottom half
    rank = mom.rank(axis=1, pct=True)
    weights = pd.DataFrame(0.0, index=mom.index, columns=mom.columns)
    weights[rank > 0.75] = 1.0 / (rank > 0.75).sum(axis=1).replace(0, 1)
    weights[rank < 0.25] = -1.0 / (rank < 0.25).sum(axis=1).replace(0, 1)
    weights = weights.shift(1)  # no lookahead
    
    pnl = (weights * returns).sum(axis=1)
    cost = weights.diff().abs().sum(axis=1) * 0.0001
    return (pnl - cost).dropna()

# ═══════════════════════════════════════════════════════════════
# RUN ALL TESTS
# ═══════════════════════════════════════════════════════════════
print('='*80)
print('MULTI-STRATEGY SCANNER — Finding edges for 4-8%/month')
print('='*80)

h1_pairs = ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY', 'USOIL']
d1_pairs = ['EURUSD', 'GBPUSD', 'AUDUSD', 'USDJPY', 'XAUUSD', 'US500', 'US100']

# ── TEST 1: Mean Reversion on H1 ──
print('\n' + '='*80)
print('STRATEGY 1: INTRADAY MEAN REVERSION (RSI + BB, H1)')
print('='*80)
for pair in h1_pairs:
    df = load_h1(pair)
    if df is None:
        print(f'  {pair}: no H1 data')
        continue
    pnl = strat_mean_reversion(df)
    stats(pnl, pair)

# ── TEST 2: Session Momentum ──
print('\n' + '='*80)
print('STRATEGY 2: SESSION MOMENTUM (London open breakout, H1)')
print('='*80)
for pair in h1_pairs:
    df = load_h1(pair)
    if df is None:
        continue
    pnl = strat_session_momentum(df)
    stats(pnl, pair)

# ── TEST 3: Volatility Breakout ──
print('\n' + '='*80)
print('STRATEGY 3: VOLATILITY BREAKOUT (ATR squeeze, H1)')
print('='*80)
for pair in h1_pairs:
    df = load_h1(pair)
    if df is None:
        continue
    pnl = strat_vol_breakout(df)
    stats(pnl, pair)

# ── TEST 4: Carry Trade (D1) ──
print('\n' + '='*80)
print('STRATEGY 4: CARRY TRADE PROXY (D1 momentum rank)')
print('='*80)
d1_prices = {}
for p in d1_pairs:
    df = load_d1(p)
    if df is not None:
        d1_prices[p] = df['Close']
if len(d1_prices) >= 3:
    prices_df = pd.DataFrame(d1_prices).dropna()
    pnl = strat_carry_trade_d1(d1_prices)
    stats(pnl, 'Multi-pair carry proxy')

# ── TEST 5: Parameter sweeps for best strategies ──
print('\n' + '='*80)
print('PARAMETER SWEEP — Mean Reversion on XAUUSD H1')
print('='*80)
df = load_h1('XAUUSD')
if df is not None:
    for rsi_os in [25, 30, 35]:
        for bb_std in [1.5, 2.0, 2.5]:
            for rr in [1.5, 2.0, 3.0]:
                pnl = strat_mean_reversion(df, rsi_oversold=rsi_os, rsi_overbought=100-rsi_os,
                                          bb_std=bb_std, rr=rr)
                if len(pnl) > 30:
                    cum = (1 + pnl).cumprod()
                    sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
                    med_mo = pnl.resample('ME').sum().median() * 100
                    print(f'  RSI({rsi_os}/{100-rsi_os}) BB({bb_std}) RR({rr})  '
                          f'Sh={sh:+.2f}  MedMo={med_mo:.2f}%  Trades={len(pnl)}')

print('\n' + '='*80)
print('PARAMETER SWEEP — Session Momentum on EURUSD H1')
print('='*80)
df = load_h1('EURUSD')
if df is not None:
    for lb in [4, 6, 8]:
        for atr_m in [0.5, 1.0, 1.5]:
            for rr in [1.5, 2.0, 3.0]:
                pnl = strat_session_momentum(df, lookback=lb, atr_mult=atr_m, rr=rr)
                if len(pnl) > 30:
                    cum = (1 + pnl).cumprod()
                    sh = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0
                    med_mo = pnl.resample('ME').sum().median() * 100
                    print(f'  LB({lb}) ATR({atr_m}) RR({rr})  '
                          f'Sh={sh:+.2f}  MedMo={med_mo:.2f}%  Trades={len(pnl)}')
