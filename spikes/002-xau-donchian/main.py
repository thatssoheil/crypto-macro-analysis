"""
Spike 002: XAUUSD Donchian D1 channel breakout + ATR trail (vectorized).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
COST = 0.0003  # gold CFD rough RT


def load() -> pd.DataFrame:
    for name in ("XAUUSD_D1.csv",):
        p = DATA / name
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            return df[["Open", "High", "Low", "Close"]].dropna()
    raise SystemExit("Need data/XAUUSD_D1.csv — run yahoo_fetch first")


def atr(df, n=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()


def run(df: pd.DataFrame, n: int, atr_mult: float) -> pd.Series:
    up = df["High"].rolling(n).max().shift(1)
    dn = df["Low"].rolling(n).min().shift(1)
    a = atr(df).shift(1)
    close = df["Close"]
    ret = close.pct_change()

    pos = pd.Series(0.0, index=df.index)
    state = 0
    stop = np.nan
    for i in range(len(df)):
        if np.isnan(up.iloc[i]) or np.isnan(a.iloc[i]):
            pos.iloc[i] = state
            continue
        c = close.iloc[i]
        if state == 0:
            if c > up.iloc[i]:
                state = 1
                stop = c - atr_mult * a.iloc[i]
            elif c < dn.iloc[i]:
                state = -1
                stop = c + atr_mult * a.iloc[i]
        elif state == 1:
            stop = max(stop, c - atr_mult * a.iloc[i])
            if c < stop or c < dn.iloc[i]:
                state = -1 if c < dn.iloc[i] else 0
                if state == -1:
                    stop = c + atr_mult * a.iloc[i]
        elif state == -1:
            stop = min(stop, c + atr_mult * a.iloc[i])
            if c > stop or c > up.iloc[i]:
                state = 1 if c > up.iloc[i] else 0
                if state == 1:
                    stop = c - atr_mult * a.iloc[i]
        pos.iloc[i] = state

    pnl = pos.shift(1).fillna(0) * ret - pos.shift(1).abs().fillna(0) * (COST / 5)
    # cost only on flips approx
    flips = pos.diff().abs().fillna(0) > 0
    pnl = pos.shift(1).fillna(0) * ret
    pnl = pnl - flips.astype(float) * COST
    return pnl.fillna(0.0)


def stats(pnl):
    t = pnl[pnl != 0]
    if len(t) < 20:
        return dict(n=len(t), sharpe=0, ret=0, dd=0, pos_m=0)
    cum = (1 + pnl).cumprod()
    dd = (cum / cum.cummax() - 1).min()
    sh = t.mean() / t.std() * np.sqrt(252) if t.std() > 0 else 0
    m = pnl.resample("ME").sum()
    return dict(
        n=int((pnl != 0).sum()),
        sharpe=float(sh),
        ret=float(cum.iloc[-1] - 1) * 100,
        dd=float(dd) * 100,
        pos_m=float((m > 0).mean()) * 100,
        med_m=float(m.median()) * 100,
    )


def main():
    df = load()
    is_ = df["2006-01-01":"2018-12-31"]
    oos = df["2019-01-01":"2022-12-31"]
    hold = df["2023-01-01":]

    best = (-1e9, 40, 3.0)
    for n in (20, 40, 55, 80):
        for am in (2.0, 3.0, 4.0):
            s = stats(run(is_, n, am))
            if s["n"] < 100:
                continue
            if s["sharpe"] > best[0]:
                best = (s["sharpe"], n, am)

    _, n, am = best
    print(f"Spike 002 XAU Donchian | best IS n={n} atr_mult={am} sharpe={best[0]:.3f}")
    for label, part in [("IS", is_), ("OOS", oos), ("HOLD", hold)]:
        s = stats(run(part, n, am))
        print(f"  {label}: Sharpe {s['sharpe']:.3f} Ret {s['ret']:.1f}% DD {s['dd']:.1f}% "
              f"posM {s['pos_m']:.0f}% medM {s.get('med_m',0):.2f}% n_days={s['n']}")

    s_oos = stats(run(oos, n, am))
    v = "VALIDATED" if s_oos["sharpe"] >= 0.6 and s_oos["dd"] > -35 else (
        "PARTIAL" if s_oos["sharpe"] >= 0.3 else "INVALIDATED"
    )
    print("VERDICT:", v)
    print("SPIKE_002_DONE", v)


if __name__ == "__main__":
    main()
