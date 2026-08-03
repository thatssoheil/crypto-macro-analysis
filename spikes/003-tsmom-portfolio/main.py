"""
Spike 003: Multi-Asset Time-Series Momentum + Carver Volatility Targeting
Tests a diversified portfolio of FX, Metals, Energy, and Indices.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA = Path("data")

def load_data():
    symbols = [
        "US30", "US500", "US100", "GER40", "UK100", "JP225", 
        "XAUUSD", "XAGUSD", "USOIL", "UKOIL", 
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "AUDCAD", "NZDUSD"
    ]
    dfs = {}
    for sym in symbols:
        p = DATA / f"{sym}_D1.csv"
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            dfs[sym] = df['Close']
    return pd.DataFrame(dfs).dropna(how='all').ffill()

def run_tsmom_portfolio():
    prices = load_data()
    returns = prices.pct_change()
    
    # 1. Volatility calculation (EWMA, ~36 day span per Carver)
    vol = returns.ewm(span=36).std() * np.sqrt(252)
    
    # 2. Trend signals (blend of 3, 6, and 12 month momentum)
    mom3 = prices.pct_change(63)   # ~3 months
    mom6 = prices.pct_change(126)  # ~6 months
    mom12 = prices.pct_change(252) # ~12 months
    
    # Continuous signal: average of signs of momentum
    signal = (np.sign(mom3) + np.sign(mom6) + np.sign(mom12)) / 3.0
    
    # 3. Position Sizing (Targeting 10% annualized vol per asset)
    target_vol = 0.10
    # Position weight = TargetVol / AssetVol * Signal
    # Shift by 1 day to avoid lookahead bias
    weights = (target_vol / vol).replace([np.inf, -np.inf], 0) * signal
    weights = weights.shift(1)
    
    # 4. Cap leverage per asset to avoid insane sizes during zero-vol periods
    weights = weights.clip(-3, 3) 
    
    # 5. Portfolio Returns
    # Divide by number of assets to maintain overall portfolio target vol
    num_assets = len(prices.columns)
    port_returns = (weights * returns).sum(axis=1) / num_assets
    
    # Deduct rough transaction costs (1 bps per daily turnover)
    turnover = weights.diff().abs().sum(axis=1) / num_assets
    port_returns = port_returns - (turnover * 0.0001)
    
    return port_returns.dropna()

def stats(pnl, label):
    cum = (1 + pnl).cumprod()
    ret = (cum.iloc[-1] - 1) * 100
    cagr = ((cum.iloc[-1])**(252/len(pnl)) - 1) * 100
    sh = pnl.mean() / pnl.std() * np.sqrt(252)
    dd = (cum / cum.cummax() - 1).min() * 100
    
    print(f"=== {label} ===")
    print(f"CAGR (Annualized): {cagr:.2f}%")
    print(f"Total Return:      {ret:.2f}%")
    print(f"Sharpe Ratio:      {sh:.3f}")
    print(f"Max Drawdown:      {dd:.2f}%")
    print(f"Positive Months:   {(pnl.resample('ME').sum() > 0).mean()*100:.1f}%")
    print()

def main():
    print("Loading 17 assets and running Multi-Asset Time-Series Momentum...\n")
    pnl = run_tsmom_portfolio()
    
    stats(pnl, "FULL HISTORY (2007-2026)")
    stats(pnl['2015-01-01':'2019-12-31'], "IN SAMPLE (2015-2019)")
    stats(pnl['2020-01-01':'2023-12-31'], "OUT OF SAMPLE (2020-2023)")
    stats(pnl['2024-01-01':], "HOLDOUT (2024+)")

if __name__ == "__main__":
    main()
