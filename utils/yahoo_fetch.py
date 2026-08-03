"""Fetch D1/W1/H1 from Yahoo and map to FTMO-style names."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yfinance as yf

# Yahoo ticker -> FTMO-ish name
DEFAULT_MAP = {
    "^DJI": "US30",
    "^GSPC": "US500",
    "^IXIC": "US100",
    "^GDAXI": "GER40",
    "^FTSE": "UK100",
    "^N225": "JP225",
    "GC=F": "XAUUSD",
    "SI=F": "XAGUSD",
    "CL=F": "USOIL",
    "BZ=F": "UKOIL",
    "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD",
    "USDJPY=X": "USDJPY",
    "AUDUSD=X": "AUDUSD",
    "USDCAD=X": "USDCAD",
    "AUDCAD=X": "AUDCAD",
    "NZDUSD=X": "NZDUSD",
}


def fetch_one(ticker: str, name: str, interval: str, period: str, out_dir: Path) -> int:
    df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False)
    if df is None or df.empty:
        print(f"{name} ({ticker}): EMPTY")
        return 0
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.index = pd.to_datetime(df.index, utc=True)
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[cols].dropna(subset=["Open", "High", "Low", "Close"])
    tf = {"1d": "D1", "1wk": "W1", "1h": "H1"}.get(interval, interval)
    path = out_dir / f"{name}_{tf}.csv"
    df.to_csv(path)
    print(f"{name} {tf}: {len(df)} rows {df.index[0].date()} -> {df.index[-1].date()} -> {path}")
    return len(df)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", default=",".join(DEFAULT_MAP.keys()))
    p.add_argument("--interval", default="1d", choices=["1d", "1wk", "1h"])
    p.add_argument("--period", default="20y")
    p.add_argument("--out-dir", default="data")
    args = p.parse_args()

    if args.interval == "1h" and args.period in ("20y", "10y", "max"):
        args.period = "2y"  # Yahoo H1 cap

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    total = 0
    for t in [x.strip() for x in args.tickers.split(",") if x.strip()]:
        name = DEFAULT_MAP.get(t, t.replace("=X", "").replace("^", "").replace("=F", ""))
        total += fetch_one(t, name, args.interval, args.period, out)
    print(f"ALL DONE total_rows={total}")


if __name__ == "__main__":
    main()
