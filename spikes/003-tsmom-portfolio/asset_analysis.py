"""
Asset-by-Asset Trend Analysis
Isolates which FTMO assets actually have a trend-following edge.
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

def analyze_asset(prices, sym):
    returns = prices.pct_change()
    vol = returns.ewm(span=36).std() * np.sqrt(252)
    
    mom3 = prices.pct_change(63)
    mom6 = prices.pct_change(126)
    mom12 = prices.pct_change(252)
    
    signal = (np.sign(mom3) + np.sign(mom6) + np.sign(mom12)) / 3.0
    
    # Target 10% vol
    weights = (0.10 / vol).replace([np.inf, -np.inf], 0) * signal
    weights = weights.shift(1).clip(-3, 3)
    
    pnl = (weights * returns) - (weights.diff().abs() * 0.0001)
    pnl = pnl.dropna()
    
    if len(pnl) < 252: return None
    
    sh = pnl.mean() / pnl.std() * np.sqrt(252)
    cum = (1 + pnl).cumprod()
    cagr = ((cum.iloc[-1])**(252/len(pnl)) - 1) * 100
    
    return {'Symbol': sym, 'Sharpe': sh, 'CAGR_%': cagr}

def main():
    prices = load_data()
    results = []
    
    for sym in prices.columns:
        res = analyze_asset(prices[sym], sym)
        if res: results.append(res)
        
    df_res = pd.DataFrame(results).sort_values('Sharpe', ascending=False)
    print("=== TREND FOLLOWING EDGE BY ASSET (Targeting 10% Volatility) ===")
    print(df_res.to_string(index=False))

if __name__ == "__main__":
    main()
