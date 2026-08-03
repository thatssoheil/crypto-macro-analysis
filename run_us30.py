#!/usr/bin/env python3
"""Run US30 open-drive (D1 vectorized) or H1 ORB (backtesting.py). Target: US30.cash"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from backtesting import Backtest

from strategies.us30_open_drive import US30SessionORB

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
COST_RT = 0.0002  # 2 bps RT proxy until FTMO spread known


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    cols = {}
    for c in df.columns:
        cl = str(c).lower()
        if cl == "open":
            cols[c] = "Open"
        elif cl == "high":
            cols[c] = "High"
        elif cl == "low":
            cols[c] = "Low"
        elif cl == "close":
            cols[c] = "Close"
        elif cl in ("volume", "tick_volume"):
            cols[c] = "Volume"
    df = df.rename(columns=cols)
    if "Volume" not in df.columns:
        df["Volume"] = 0
    out = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    return out  # type: ignore[return-value]


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()


def d1_open_drive_pnl(df: pd.DataFrame, entry_z: float = 0.0, atr_sl: float = 1.5) -> pd.Series:
    std = df["Close"].pct_change().rolling(90).std().shift(1)
    prev_h, prev_l, prev_c = df["High"].shift(1), df["Low"].shift(1), df["Close"].shift(1)
    a = atr(df).shift(1)
    op, cl = df["Open"], df["Close"]
    long_gap = op > prev_h * (1 + entry_z * std)
    short_gap = op < prev_l * (1 - entry_z * std)
    drive_up = (op > prev_c) & ((op - prev_c) > 0.1 * a) & ~long_gap & ~short_gap
    drive_dn = (op < prev_c) & ((prev_c - op) > 0.1 * a) & ~long_gap & ~short_gap
    pos = pd.Series(0.0, index=df.index)
    pos[long_gap | drive_up] = 1.0
    pos[short_gap | drive_dn] = -1.0
    raw = pos * (cl - op) / op - pos.abs() * COST_RT
    return raw.where(pos != 0, 0.0).fillna(0.0)


def summarize(pnl: pd.Series, label: str) -> None:
    t = pnl[pnl != 0]
    if len(t) < 5:
        print(label, "too few trades", len(t))
        return
    cum = (1 + pnl).cumprod()
    sh = float(t.mean() / t.std() * np.sqrt(252)) if t.std() > 0 else 0.0
    dd = float((cum / cum.cummax() - 1).min() * 100)
    ret = float((cum.iloc[-1] - 1) * 100)
    monthly = pnl.resample("ME").sum()
    print(f"{label}")
    print(f"  Return: {ret:.2f}%  Sharpe: {sh:.3f}  MaxDD: {dd:.2f}%")
    print(f"  Trades: {len(t)}  WR: {(t>0).mean()*100:.1f}%  pos months: {(monthly>0).mean()*100:.0f}%  med month: {monthly.median()*100:.2f}%")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="")
    p.add_argument("--mode", choices=["d1", "h1orb"], default="d1")
    p.add_argument("--cash", type=float, default=100_000)
    p.add_argument("--commission", type=float, default=0.0002)
    args = p.parse_args()

    candidates = []
    if args.csv:
        candidates.append(Path(args.csv))
    candidates += [
        DATA / "ftmo" / "US30_cash_D1.csv",
        DATA / "US30_cash_D1.csv",
        DATA / "ftmo" / "US30_cash_H1.csv",
        DATA / "US30_D1.csv",
    ]
    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        raise SystemExit("no US30 CSV found — export from MT5 or use data/US30_D1.csv")

    df = load_csv(path)
    print(f"symbol target: US30.cash")
    print(f"data: {path} rows={len(df)} {df.index[0]} -> {df.index[-1]}")

    if args.mode == "d1":
        pnl = d1_open_drive_pnl(df)
        summarize(pnl, "FULL")
        summarize(pnl["2010-01-01":"2018-12-31"], "IS 2010-18")
        summarize(pnl["2019-01-01":"2022-12-31"], "OOS 2019-22")
        summarize(pnl["2023-01-01":], "HOLD 2023+")
        # leverage-ish: 1% risk not modeled; report raw open-close
        print("ponytail: costs=2bps RT proxy; size=1 unit notional; FTMO CFD spread TBD")
        return

    # H1 ORB via backtesting — needs H1 bars
    if "H1" not in path.name.upper() and "h1" not in path.name:
        h1 = DATA / "ftmo" / "US30_cash_H1.csv"
        if h1.exists():
            path = h1
            df = load_csv(path)
            print(f"switched to {path}")
        else:
            raise SystemExit("h1orb needs H1 CSV (run ExportBars on US30.cash)")

    bt = Backtest(
        df,
        US30SessionORB,
        cash=args.cash,
        commission=args.commission,
        exclusive_orders=True,
        finalize_trades=True,
        margin=0.01,  # 1:100 style CFD margin proxy
    )
    stats = bt.run()
    for k in ["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "Win Rate [%]", "# Trades", "Profit Factor"]:
        print(f"{k}: {stats.get(k)}")


if __name__ == "__main__":
    main()
