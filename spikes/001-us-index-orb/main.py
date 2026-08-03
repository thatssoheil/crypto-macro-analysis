"""
Spike 001: US Index Opening Range Breakout (daily proxy).

Given daily OHLC proxy for US30/US500/US100,
When we trade open-direction momentum with range filter + ATR stop,
Then report IS/OOS Sharpe, DD, monthly stats and VERDICT.

Note: True 09:30-09:45 ORB needs M15. This D1 spike tests whether
equity-index directional open-to-close edge exists at all (same family
as Chan gap / open drive). If VALIDATED, next step is M15 ORB on FTMO CSV.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

# Pre-registered only — no fishing beyond this grid
ENTRY_Z_GRID = [0.0, 0.05, 0.1]
ATR_SL_GRID = [1.5, 2.0, 3.0]
COST_RT = 0.0002  # ~2 bps round-turn proxy on index CFD


def load(sym: str) -> pd.DataFrame:
    path = DATA / f"{sym}_D1.csv"
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df[["Open", "High", "Low", "Close"]].dropna()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()


def run_orb(df: pd.DataFrame, entry_z: float, atr_sl: float) -> pd.Series:
    """
    Signal at open vs prior day range + vol buffer.
    Long if open gaps above prior high * (1 + z*std)
    Short if open gaps below prior low * (1 - z*std)
    Else: open-drive — long if open > prior close, short if open < prior close
      only when |open-prev_close| > 0.1*ATR (avoid noise)
    Exit: same-day close. SL conceptual via atr_sl for position sizing report only
    (PnL uses open->close; stop approximated by clipping loss to -atr_sl*ATR/open).
    """
    std = df["Close"].pct_change().rolling(90).std().shift(1)
    prev_h = df["High"].shift(1)
    prev_l = df["Low"].shift(1)
    prev_c = df["Close"].shift(1)
    a = atr(df).shift(1)
    op, cl = df["Open"], df["Close"]

    long_gap = op > prev_h * (1 + entry_z * std)
    short_gap = op < prev_l * (1 - entry_z * std)
    drive_up = (op > prev_c) & ((op - prev_c) > 0.1 * a) & ~long_gap & ~short_gap
    drive_dn = (op < prev_c) & ((prev_c - op) > 0.1 * a) & ~long_gap & ~short_gap

    pos = pd.Series(0.0, index=df.index)
    pos[long_gap | drive_up] = 1.0
    pos[short_gap | drive_dn] = -1.0

    raw = pos * (cl - op) / op
    # Approximate stop: cap adverse move at atr_sl * ATR / open
    max_loss = -(atr_sl * a / op)
    raw = raw.clip(lower=max_loss)
    raw = raw - pos.abs() * COST_RT
    raw = raw.where(pos != 0, 0.0)
    return raw.fillna(0.0)


def stats(pnl: pd.Series) -> dict:
    traded = pnl[pnl != 0]
    if len(traded) < 5:
        return {"n": len(traded), "ret": 0, "sharpe": 0, "dd": 0, "win": 0, "pos_m": 0}
    cum = (1 + pnl).cumprod()
    dd = (cum / cum.cummax() - 1).min()
    sharpe = traded.mean() / traded.std() * np.sqrt(252) if traded.std() > 0 else 0
    monthly = pnl.resample("ME").sum()
    pos_m = (monthly > 0).mean() if len(monthly) else 0
    return {
        "n": int((pnl != 0).sum()),
        "ret": float(cum.iloc[-1] - 1) * 100,
        "sharpe": float(sharpe),
        "dd": float(dd) * 100,
        "win": float((traded > 0).mean()) * 100,
        "pos_m": float(pos_m) * 100,
        "med_m": float(monthly.median()) * 100,
    }


def split(df: pd.DataFrame):
    # IS 2010-2018, OOS 2019-2022, holdout 2023+
    is_ = df["2010-01-01":"2018-12-31"]
    oos = df["2019-01-01":"2022-12-31"]
    hold = df["2023-01-01":]
    return is_, oos, hold


def best_params(df_is: pd.DataFrame) -> tuple[float, float, float]:
    best = (-1e9, 0.0, 2.0)
    for ez in ENTRY_Z_GRID:
        for sl in ATR_SL_GRID:
            s = stats(run_orb(df_is, ez, sl))
            if s["n"] < 50:
                continue
            score = s["sharpe"]
            if score > best[0]:
                best = (score, ez, sl)
    return best[1], best[2], best[0]


def main():
    symbols = [s for s in ("US30", "US500", "US100") if (DATA / f"{s}_D1.csv").exists()]
    if not symbols:
        print("NO DATA — run utils/yahoo_fetch.py first")
        return

    print("Spike 001 — US Index ORB / open-drive (D1 proxy)")
    print("Costs:", COST_RT, "RT | grids entry_z", ENTRY_Z_GRID, "atr_sl", ATR_SL_GRID)
    print()

    any_ok = False
    rows = []
    for sym in symbols:
        df = load(sym)
        is_, oos, hold = split(df)
        ez, sl, is_sh = best_params(is_)
        s_is = stats(run_orb(is_, ez, sl))
        s_oos = stats(run_orb(oos, ez, sl))
        s_h = stats(run_orb(hold, ez, sl)) if len(hold) > 50 else None

        ok = s_oos["sharpe"] >= 0.8 and s_oos["dd"] > -25 and s_oos["n"] >= 30
        any_ok = any_ok or ok
        verdict = "VALIDATED" if ok else ("PARTIAL" if s_oos["sharpe"] >= 0.4 else "INVALIDATED")

        print(f"=== {sym} === params entry_z={ez} atr_sl={sl} (IS sharpe pick {is_sh:.3f})")
        print(f"  IS   2010-18: Sharpe {s_is['sharpe']:.3f} Ret {s_is['ret']:.1f}% DD {s_is['dd']:.1f}% "
              f"WR {s_is['win']:.0f}% n={s_is['n']} posM {s_is['pos_m']:.0f}% medM {s_is['med_m']:.2f}%")
        print(f"  OOS  2019-22: Sharpe {s_oos['sharpe']:.3f} Ret {s_oos['ret']:.1f}% DD {s_oos['dd']:.1f}% "
              f"WR {s_oos['win']:.0f}% n={s_oos['n']} posM {s_oos['pos_m']:.0f}% medM {s_oos['med_m']:.2f}%")
        if s_h:
            print(f"  HOLD 2023+ : Sharpe {s_h['sharpe']:.3f} Ret {s_h['ret']:.1f}% DD {s_h['dd']:.1f}% "
                  f"WR {s_h['win']:.0f}% n={s_h['n']} posM {s_h['pos_m']:.0f}% medM {s_h['med_m']:.2f}%")
        print(f"  VERDICT: {verdict}")
        print()
        rows.append((sym, verdict, s_oos))

    # Portfolio equal weight OOS on validated/partial
    print("=== Equal-weight portfolio OOS (all symbols, best IS params each) ===")
    pnls = []
    for sym in symbols:
        df = load(sym)
        is_, oos, _ = split(df)
        ez, sl, _ = best_params(is_)
        p = run_orb(oos, ez, sl)
        pnls.append(p)
    # align
    port = pd.concat(pnls, axis=1).fillna(0).mean(axis=1)
    sp = stats(port)
    print(f"  OOS port: Sharpe {sp['sharpe']:.3f} Ret {sp['ret']:.1f}% DD {sp['dd']:.1f}% "
          f"posM {sp['pos_m']:.0f}% medM {sp['med_m']:.2f}%")
    port_v = "VALIDATED" if sp["sharpe"] >= 0.8 and sp["dd"] > -25 else (
        "PARTIAL" if sp["sharpe"] >= 0.4 else "INVALIDATED"
    )
    print(f"  PORT VERDICT: {port_v}")
    print()
    print("NOTE: D1 open-drive is proxy only. True ORB needs M15 FTMO data if promising.")
    print("SPIKE_001_DONE", port_v)


if __name__ == "__main__":
    main()
