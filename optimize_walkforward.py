#!/usr/bin/env python3
"""Walk-forward validation of TSMOM optimization candidates."""
import pandas as pd
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

DATA = Path(__file__).parent / "data"

def load(symbols):
    prices = {}
    for s in symbols:
        p = DATA / f'{s}_D1.csv'
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            prices[s] = df['Close'].dropna()
    return pd.DataFrame(prices).dropna(how='any')

def backtest_core(prices, lookbacks=(63,126,252), target_vol=0.15, max_lev=5.0,
                  cost_per_unit=0.0001, vol_span=36, hold_days=0):
    returns = prices.pct_change()
    vol = returns.ewm(span=vol_span).std() * np.sqrt(252)
    signals = [np.sign(prices.pct_change(lb)) for lb in lookbacks]
    signal = sum(signals) / len(signals)
    n = len(prices.columns)
    weights = (target_vol / vol).replace([np.inf,-np.inf],0) * signal / n
    weights = weights.shift(1).clip(-max_lev, max_lev)

    if hold_days > 0:
        for col in weights.columns:
            w = weights[col]
            result = pd.Series(np.nan, index=w.index)
            last_val = np.nan
            days_since = 999
            for i in range(len(w)):
                val = w.iloc[i]
                if pd.notna(val):
                    if days_since >= hold_days:
                        last_val = val
                        days_since = 0
                    result.iloc[i] = last_val
            weights[col] = result

    turnover = weights.diff().abs().sum(axis=1) / n
    cost = turnover * cost_per_unit
    pnl = (weights * returns).sum(axis=1) - cost
    return pnl.dropna()

def walk_forward(prices, config, label=""):
    pnl = backtest_core(prices, **config)
    start = pnl.index[0]
    end = pnl.index[-1]
    windows = []
    cur = start
    while cur < end:
        train_end = cur + pd.DateOffset(years=3)
        test_end = train_end + pd.DateOffset(years=1)
        if test_end > end:
            test_end = end
        if train_end >= end:
            break
        test_pnl = pnl[(pnl.index >= train_end) & (pnl.index < test_end)]
        windows.append(test_pnl)
        cur = train_end

    print(f"\n  {label}")
    print(f"  {'Window':30s} {'Sharpe':>8s} {'CAGR':>8s} {'MaxDD':>8s} {'WinMo':>7s}")
    print(f"  {'-'*65}")

    sharpes, cagrs, dds, wins = [], [], [], []

    for wp in windows:
        if len(wp) < 60:
            continue
        cum = (1 + wp).cumprod()
        sh = wp.mean() / wp.std() * np.sqrt(252) if wp.std() > 0 else 0
        cagr = ((cum.iloc[-1])**(252/len(wp)) - 1) * 100
        dd = (cum / cum.cummax() - 1).min() * 100
        monthly = wp.resample('ME').sum() * 100
        win = (monthly > 0).mean() * 100
        sharpes.append(sh)
        cagrs.append(cagr)
        dds.append(dd)
        wins.append(win)
        print(f"  {str(wp.index[0].date())} -> {str(wp.index[-1].date()):30s} {sh:+8.2f} {cagr:+7.1f}% {dd:7.1f}% {win:6.0f}%")

    if sharpes:
        avg_sh = np.mean(sharpes)
        pos_sh = sum(1 for s in sharpes if s > 0) / len(sharpes)
        avg_cagr = np.mean(cagrs)
        worst_dd = min(dds)
        avg_win = np.mean(wins)
        print(f"  {'-'*65}")
        print(f"  {'AVG':30s} {avg_sh:+8.2f} {avg_cagr:+7.1f}% {worst_dd:7.1f}% {avg_win:6.0f}%")
        print(f"  Positive Sharpe windows: {pos_sh*100:.0f}%  ({sum(1 for s in sharpes if s > 0)}/{len(sharpes)})")
    return sharpes

print("="*80)
print("WALK-FORWARD VALIDATION - 3yr train / 1yr test rolling windows")
print("="*80)

configs = [
    ("CURRENT: 4 assets, daily rebalance",
     ['XAUUSD','US100','US500','USDJPY'],
     {"lookbacks":(63,126,252),"target_vol":0.15,"hold_days":0}),
    ("CURRENT HOLD7: 4 assets, 7d rebalance",
     ['XAUUSD','US100','US500','USDJPY'],
     {"lookbacks":(63,126,252),"target_vol":0.15,"hold_days":7}),
    ("DEDUP: 3 assets (XAU+US500+JPY), daily",
     ['XAUUSD','US500','USDJPY'],
     {"lookbacks":(63,126,252),"target_vol":0.15,"hold_days":0}),
    ("DEDUP HOLD7: 3 assets, 7d rebalance",
     ['XAUUSD','US500','USDJPY'],
     {"lookbacks":(63,126,252),"target_vol":0.15,"hold_days":7}),
    ("DIVERSIFY: 4 assets (XAU+US500+JPY+OIL), daily",
     ['XAUUSD','US500','USDJPY','USOIL'],
     {"lookbacks":(63,126,252),"target_vol":0.15,"hold_days":0}),
    ("DIVERSIFY HOLD7: 4 assets, 7d rebalance",
     ['XAUUSD','US500','USDJPY','USOIL'],
     {"lookbacks":(63,126,252),"target_vol":0.15,"hold_days":7}),
    ("BOND HEDGE: 4 assets (XAU+US100+JPY+BOND30Y), 7d",
     ['XAUUSD','US100','USDJPY','US30YBOND'],
     {"lookbacks":(63,126,252),"target_vol":0.15,"hold_days":7}),
    ("BOND HEDGE: 5 assets (XAU+US500+JPY+OIL+BOND30Y), 7d",
     ['XAUUSD','US500','USDJPY','USOIL','US30YBOND'],
     {"lookbacks":(63,126,252),"target_vol":0.15,"hold_days":7}),
]

all_results = {}
for label, syms, config in configs:
    p = load(syms)
    result = walk_forward(p, config, label=label)
    all_results[label] = result

print("\n" + "="*80)
print("SUMMARY: Walk-Forward Comparison")
print("="*80)
print(f"  {'Strategy':58s} {'Avg Sh':>7s} {'Pos%':>5s}")
print(f"  {'-'*72}")
for label, sh in all_results.items():
    if sh:
        avg = np.mean(sh)
        pos = sum(1 for s in sh if s > 0) / len(sh) * 100
        print(f"  {label:58s} {avg:+7.2f} {pos:4.0f}%")
