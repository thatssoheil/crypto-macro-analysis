"""
Focused TSMOM Portfolio (The 'Trending Four')
Assets: XAUUSD, US100, US500, USDJPY
Target Vol: 15%
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA = Path("data")

def load_data():
    symbols = ["XAUUSD", "US100", "US500", "USDJPY"]
    dfs = {}
    for sym in symbols:
        p = DATA / f"{sym}_D1.csv"
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            dfs[sym] = df['Close']
    return pd.DataFrame(dfs).dropna(how='any')

def run_portfolio():
    prices = load_data()
    returns = prices.pct_change()
    
    # Carver EWMA vol
    vol = returns.ewm(span=36).std() * np.sqrt(252)
    
    # Trend signals
    mom3 = prices.pct_change(63)
    mom6 = prices.pct_change(126)
    mom12 = prices.pct_change(252)
    signal = (np.sign(mom3) + np.sign(mom6) + np.sign(mom12)) / 3.0
    
    # 15% Vol Target per asset
    weights = (0.15 / vol).replace([np.inf, -np.inf], 0) * signal
    weights = weights.shift(1).clip(-5, 5)  # Allow a bit more leverage
    
    # Portfolio returns (equal weight allocation to the 4 strategies)
    port_returns = (weights * returns).sum(axis=1) / len(prices.columns)
    
    # Costs
    turnover = weights.diff().abs().sum(axis=1) / len(prices.columns)
    port_returns = port_returns - (turnover * 0.0001)
    
    return port_returns.dropna()

def stats(pnl, label):
    cum = (1 + pnl).cumprod()
    ret = (cum.iloc[-1] - 1) * 100
    cagr = ((cum.iloc[-1])**(252/len(pnl)) - 1) * 100
    sh = pnl.mean() / pnl.std() * np.sqrt(252)
    dd = (cum / cum.cummax() - 1).min() * 100
    
    monthly = pnl.resample('ME').sum() * 100
    win_months = (monthly > 0).mean() * 100
    best_month = monthly.max()
    med_month = monthly.median()
    
    print(f"=== {label} ===")
    print(f"Sharpe Ratio:    {sh:.2f}")
    print(f"CAGR:            {cagr:.2f}%")
    print(f"Max Drawdown:    {dd:.2f}%")
    print(f"Win Months:      {win_months:.1f}%")
    print(f"Median Month:    {med_month:.2f}%")
    print(f"Best Month:      {best_month:.2f}%")
    print()

def main():
    pnl = run_portfolio()
    stats(pnl, "FULL HISTORY (2007-2026)")
    stats(pnl['2015-01-01':'2019-12-31'], "IN SAMPLE (2015-2019)")
    stats(pnl['2020-01-01':'2023-12-31'], "OUT OF SAMPLE (2020-2023)")
    stats(pnl['2024-01-01':], "HOLDOUT (2024+)")

if __name__ == "__main__":
    main()
