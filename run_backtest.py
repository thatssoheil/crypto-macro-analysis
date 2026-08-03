"""
Offline backtest runner — no MT5 needed.
Downloads EURUSD H1 data from Yahoo Finance (^EURUSD=X) as proxy,
or load your own CSV exported from MT5/TradingView.

Usage:
    python run_backtest.py --csv data/EURUSD_H1.csv
    python run_backtest.py --yahoo  # quick smoke test
"""
import argparse
import json
import pandas as pd
from strategies.london_breakout import LondonBreakout, run_backtest
from backtest.walk_forward import walk_forward, summarize


def load_yahoo(symbol: str = "EURUSD=X", period: str = "2y", interval: str = "1h") -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.index = pd.to_datetime(df.index, utc=True)
    return df[["Open", "High", "Low", "Close", "Volume"]]


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", help="Path to OHLCV CSV")
    p.add_argument("--yahoo", action="store_true", help="Fetch from Yahoo Finance")
    p.add_argument("--walk-forward", action="store_true", help="Run walk-forward validation")
    p.add_argument("--plot", action="store_true", help="Show backtest plot")
    args = p.parse_args()

    if args.yahoo:
        print("Fetching EURUSD H1 from Yahoo Finance...")
        df = load_yahoo()
    elif args.csv:
        df = load_csv(args.csv)
    else:
        p.print_help()
        return

    print(f"Loaded {len(df)} candles: {df.index[0]} -> {df.index[-1]}")

    if args.walk_forward:
        print("\nRunning walk-forward validation...")
        results = walk_forward(df)
        summary = summarize(results)
        print("\nWalk-forward summary:")
        print(json.dumps(summary, indent=2))
        print("\nPer-window results:")
        for r in results:
            print(f"  {r['test_start']} -> {r['test_end']} | "
                  f"Sharpe: {r['sharpe']} | Return: {r['return_pct']}% | "
                  f"DD: {r['max_dd_pct']}% | Trades: {r['trades']}")
    else:
        print("\nRunning full backtest...")
        bt, stats = run_backtest(df)
        print(stats)
        if args.plot:
            bt.plot()


if __name__ == "__main__":
    main()
