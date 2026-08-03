"""
Spike 004: AUDCAD Cointegration / Mean Reversion (Statistical Arbitrage)
"""
import numpy as np
import pandas as pd
from pathlib import Path
from statsmodels.tsa.stattools import adfuller

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

def calc_halflife(series: pd.Series) -> float:
    """Calculate half-life of mean reversion using Ornstein-Uhlenbeck process."""
    lag = series.shift(1)
    lag = lag.dropna()
    ret = series - lag
    ret = ret.dropna()
    
    # align
    lag, ret = lag.align(ret, join='inner')
    
    # Linear regression: return(t) = lambda * price(t-1)
    # We add a constant to the regression
    import statsmodels.api as sm
    X = sm.add_constant(lag)
    model = sm.OLS(ret, X)
    res = model.fit()
    
    lam = res.params.iloc[1]
    if lam >= 0:
        return np.inf  # Not mean reverting
    
    return -np.log(2) / lam

def run_mr(df, halflife, z_entry=1.5, z_exit=0.0):
    lookback = int(round(halflife))
    if lookback < 5: lookback = 5
    if lookback > 200: lookback = 200
    
    close = df['Close']
    ma = close.rolling(window=lookback).mean()
    std = close.rolling(window=lookback).std()
    z_score = (close - ma) / std
    
    # Shift signals to avoid lookahead bias
    z = z_score.shift(1)
    
    pos = pd.Series(0.0, index=df.index)
    state = 0
    for i in range(len(df)):
        if np.isnan(z.iloc[i]):
            continue
            
        # Entry
        if state == 0:
            if z.iloc[i] > z_entry:
                state = -1  # Short
            elif z.iloc[i] < -z_entry:
                state = 1   # Long
        # Exit
        elif state == 1:
            if z.iloc[i] >= z_exit:
                state = 0
        elif state == -1:
            if z.iloc[i] <= z_exit:
                state = 0
                
        pos.iloc[i] = state
        
    ret = close.pct_change()
    # PnL = holding return - 1 pip transaction cost on flips
    flips = pos.diff().abs() > 0
    pnl = pos.shift(1).fillna(0) * ret - flips * 0.0001
    return pnl.fillna(0.0)

def main():
    path = DATA / "AUDCAD_D1.csv"
    if not path.exists():
        print("Missing", path)
        return
        
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    
    print("=== AUDCAD Mean Reversion Analysis ===")
    
    # 1. Stationarity check (ADF) over the full history
    print("\n1. Stationarity (Augmented Dickey-Fuller Test)")
    adf_result = adfuller(df['Close'].dropna())
    print(f"ADF Statistic: {adf_result[0]:.4f}")
    print(f"p-value: {adf_result[1]:.4f} (must be < 0.05 to trade)")
    
    # 2. Half-life calculation
    print("\n2. Reversion Speed (Half-life)")
    hl = calc_halflife(df['Close'])
    print(f"Half-life: {hl:.1f} days")
    
    if adf_result[1] > 0.05:
        print("\nWARNING: AUDCAD is NOT statistically stationary over the full horizon. Mean reversion is dangerous here.")
        
    # 3. Strategy run
    print("\n3. Strategy Performance (Z-entry 1.5, Z-exit 0, lookback = half-life)")
    is_df = df['2006':'2018']
    oos_df = df['2019':'2022']
    hold_df = df['2023':]
    
    for label, d in [("In-Sample (2006-2018)", is_df), ("Out-of-Sample (2019-2022)", oos_df), ("Holdout (2023+)", hold_df)]:
        pnl = run_mr(d, hl)
        t = pnl[pnl != 0]
        if len(t) < 5:
            print(f"  {label}: Not enough trades")
            continue
            
        cum = (1 + pnl).cumprod()
        ret = (cum.iloc[-1] - 1) * 100
        dd = (cum / cum.cummax() - 1).min() * 100
        sh = t.mean() / t.std() * np.sqrt(252) if t.std() > 0 else 0
        print(f"  {label}:")
        print(f"    Sharpe: {sh:.2f} | Return: {ret:.1f}% | Max DD: {dd:.1f}% | Trades: {len(t)}")

if __name__ == "__main__":
    main()
