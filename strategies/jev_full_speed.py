#!/usr/bin/env python3
"""
JEV-FULL + SPEED ABLATION prototype (stateless, stdout only).

Part 1 - Jev-FULL signal (daily risk score -> size):
  Three flags (each +1 / 0 / -1, missing data -> 0) plus a continuous
  200d-MA distance tilt:
    f_trend : +1 close >= 200dMA else -1            (trend)
    f_stress: +1 VIX < 20, -1 VIX > 30, else 0      (stress)
    f_sent  : +1 F&G < 30, -1 F&G > 70, else 0      (contrarian sentiment)
    tilt    : clip(((close-MA200)/MA200)/0.20, -1, +1)
  score = f_trend + f_stress + f_sent + tilt   (range -4..+4)
  target: score >= +1.5 -> long 2x | score >= -0.5 -> long 1x
          score <  -0.5 -> SHORT 1x only if (close < MA200 AND funding < 0),
                             else cash.
  Short gate uses the funding print known at decision time (t-1 for day t).

Part 2 - SPEED ABLATION: the SAME mapping evaluated at three cadences:
  weekly: sampled on Friday close, held all next week (no intra-week switch).
  daily : decision close t-1 earns day t (house .shift(1) convention).
  4h    : btcusd_hourly_bitstamp aggregated to 4h bars (00/04/.../20 UTC);
          1200-bar MA (= 200d in time); VIX/F&G/funding-gate use the prior
          calendar day's print (a same-day daily print is not known intraday,
          so it would be lookahead); funding COST accrues the contemporaneous
          daily rate / 6 (realized cost accounting, not a signal).
  No lookahead at any cadence: weekly uses Friday close for next week,
  4h uses the prior 4h close.

Accounting (house conventions from futures_vs_spot.py):
  $10k cash 0%, isolated margin, notional = lev x equity at each (re)entry,
  mark-to-market on closes, LIQUIDATION on daily (4h-bar) low/high breach
  with mm = 0.5%, longs pay funding on open notional (shorts receive).
  No fees/slippage. Windows: full 2020-01.., last top 2021-11.., post-bear
  2023-01... Results print to stdout, nothing saved.
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "macro_dataset"
MM = 0.005
START_CASH = 10000.0


def load_daily_ohlc():
    df = pd.read_csv(DATA / "btcusd_daily_bitstamp.csv")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()[["open", "high", "low", "close"]]


def load_4h():
    h = pd.read_csv(DATA / "btcusd_hourly_bitstamp.csv")
    h["ts"] = pd.to_datetime(h["ts"], utc=True)
    h = h.set_index("ts").sort_index()
    g = h["close"]  # placeholder to keep grouping key aligned
    grp = h.index.floor("4h")
    o = h["open"].groupby(grp).first()
    hi = h["high"].groupby(grp).max()
    lo = h["low"].groupby(grp).min()
    c = h["close"].groupby(grp).last()
    px = pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c})
    px.index.name = "ts"
    return px


def load_series(name, col="value"):
    for dc in ("date", "ts"):
        try:
            df = pd.read_csv(DATA / f"{name}.csv")
        except FileNotFoundError:
            return None
        if dc in df.columns:
            df[dc] = pd.to_datetime(df[dc], utc=True)
            return df.set_index(dc).sort_index()[col]
    return None


def jev_targets(close, ma200, stress, sent, fund_gate):
    """Vectorized Jev-FULL mapping. All inputs aligned; NaN flag -> 0."""
    tr = (close - ma200)
    f_trend = pd.Series(np.sign(tr), index=close.index).fillna(0.0)
    f_stress = pd.Series(0.0, index=close.index)
    f_stress[stress < 20.0] = 1.0
    f_stress[stress > 30.0] = -1.0
    f_sent = pd.Series(0.0, index=close.index)
    f_sent[sent < 30.0] = 1.0
    f_sent[sent > 70.0] = -1.0
    dist = (close - ma200) / ma200
    tilt = (dist / 0.20).clip(-1.0, 1.0).fillna(0.0)
    score = f_trend + f_stress + f_sent + tilt
    tgt = pd.Series(0.0, index=close.index)
    tgt[score >= 1.5] = 2.0
    tgt[(score >= -0.5) & (score < 1.5)] = 1.0
    lo = score < -0.5
    gate = (close < ma200) & (fund_gate < 0)
    tgt[lo & gate] = -1.0
    tgt[lo & ~gate.fillna(False)] = 0.0
    return tgt, score


def sim_signed(px, target, lev_cap, funding_per_bar, start_cash=START_CASH):
    """Futures loop with signed-leverage targets (+2/+1/0/-1).

    target: raw (unshifted) series; position earning bar i is set at close[i-1].
    funding_per_bar: realized funding rate per bar (cost accounting).
    Returns (equity series, stats). Liquidation math mirrors futures_vs_spot.py.
    """
    close = px["close"].to_numpy(float)
    low = px["low"].to_numpy(float)
    high = px["high"].to_numpy(float)
    st = target.to_numpy(float)
    fund = funding_per_bar.reindex(px.index).fillna(0.0).to_numpy(float)
    n = len(close)
    cash, size, entry = start_cash, 0.0, 0.0
    cur_lev = 0.0
    eqs = np.zeros(n)
    funding_total, flips, entries = 0.0, 0, 0
    liq, worst_wick = [], np.inf
    n_long2x = n_long1x = n_short = 0
    for i in range(n):
        if size != 0.0 and i > 0:
            prev_close = close[i - 1]
            equity_prev = cash + size * (prev_close - entry)
            dead = False
            if size > 0:
                liq_px = (size * prev_close - equity_prev) / (size * (1 - MM))
                if low[i] <= liq_px:
                    liq.append(str(px.index[i]) + " long"); dead = True
                elif liq_px > 0:
                    worst_wick = min(worst_wick, low[i] / liq_px)
                # liq_px <= 0: equity exceeds notional, liquidation impossible; skip
                n_long2x += cur_lev == 2.0; n_long1x += cur_lev == 1.0
            else:
                liq_px = (equity_prev - size * prev_close) / (-size * (1 + MM))
                if high[i] >= liq_px:
                    liq.append(str(px.index[i]) + " short"); dead = True
                else:
                    worst_wick = min(worst_wick, liq_px / high[i])
                n_short += 1
            if dead:
                cash, size, cur_lev = 0.0, 0.0, 0.0
            else:
                cost = np.sign(size) * fund[i] * abs(size) * close[i]
                cash -= cost
                funding_total += cost
        if size == 0.0 and cash <= 0.0:
            eqs[i] = 0.0
            continue
        want = float(st[i]) if abs(float(st[i])) <= lev_cap else np.sign(st[i]) * lev_cap
        if want != cur_lev:
            flips += 1
            if size != 0.0:
                cash += size * (close[i] - entry)
                size = 0.0
            if want != 0.0 and cash > 0.0:
                notional = cash * abs(want)
                size = np.sign(want) * notional / close[i]
                entry = close[i]
                entries += 1
            cur_lev = want if (size != 0.0 or want == 0.0) else 0.0
            if want != 0.0 and size == 0.0:
                cur_lev = 0.0
        eqs[i] = cash + (size * (close[i] - entry) if size != 0.0 else 0.0)
    eq = pd.Series(eqs, index=px.index)
    return eq, {"flips": flips, "entries": entries, "funding_total": funding_total,
                "liq": liq, "worst_wick": worst_wick if np.isfinite(worst_wick) else None,
                "n_long2x": n_long2x, "n_long1x": n_long1x, "n_short": n_short}


def stats(eq, t0, t1, start_cash=START_CASH):
    final = float(eq.iloc[-1])
    years = max((t1 - t0).total_seconds() / (365.25 * 86400), 1e-9)
    cagr = ((final / start_cash) ** (1 / years) - 1) * 100 if final > 0 else -100.0
    dd = float((eq / eq.cummax() - 1).min() * 100)
    return final, cagr, dd


def main():
    btc = load_daily_ohlc()
    px4 = load_4h()
    funding = load_series("bn_funding_btc")
    vix = load_series("vix", "close")
    fng = load_series("fear_greed")
    end = min(btc.index.max(), funding.index.max())
    print("=== JEV-FULL + SPEED ABLATION (stateless prototype) ===")
    print(f"data through {end.date()} | daily {len(btc)} rows | 4h {len(px4)} bars | "
          f"funding {funding.index.min().date()}..{funding.index.max().date()}")

    close = btc["close"]
    ma200 = close.rolling(200).mean()
    tgt_d, score_d = jev_targets(close, ma200,
                                 vix.reindex(close.index).ffill(),
                                 fng.reindex(close.index).ffill(),
                                 funding.reindex(close.index).ffill())
    # weekly: Friday-close sample, held all next week
    fri = tgt_d[close.index.weekday == 4]
    tgt_w = fri.reindex(close.index).ffill().fillna(0.0)

    # 4h: same mapping, 1200-bar MA, prior-day VIX/F&G/funding gate
    c4 = px4["close"]
    ma4 = c4.rolling(1200).mean()
    daykey = (c4.index.floor("D") - pd.Timedelta(days=1))
    vix_d = vix.reindex(pd.DatetimeIndex(sorted(set(vix.index.floor("D")) | set(daykey.floor("D"))))).ffill() \
        if vix is not None else pd.Series(0.0, index=c4.index)
    fng_d = fng.reindex(pd.DatetimeIndex(sorted(set(fng.index.floor("D")) | set(daykey.floor("D"))))).ffill() \
        if fng is not None else pd.Series(0.0, index=c4.index)
    fnd_d = funding.reindex(pd.DatetimeIndex(sorted(set(funding.index.floor("D")) | set(daykey.floor("D"))))).ffill()
    tgt_4, score_4 = jev_targets(c4, ma4,
                                 pd.Series(vix_d.reindex(daykey).to_numpy(), index=c4.index),
                                 pd.Series(fng_d.reindex(daykey).to_numpy(), index=c4.index),
                                 pd.Series(fnd_d.reindex(daykey).to_numpy(), index=c4.index))
    fund_4 = pd.Series(fnd_d.reindex(c4.index.floor("D")).to_numpy(), index=c4.index) / 6.0

    # anchor check: state mix of the daily Jev-FULL target over full window
    w0full = pd.Timestamp("2020-01-01", tz="UTC")
    td = tgt_d.loc[w0full:end]
    print(f"jev_daily target mix 2020-01..: "
          + " ".join(f"{v:+.0f}x={(td == v).mean() * 100:.1f}%" for v in (2.0, 1.0, 0.0, -1.0)))

    print(f"\n{'arm':16} {'final $':>12} {'CAGR':>7} {'maxDD':>7} "
          f"{'flips':>7} {'entries':>7} {'funding $':>10} {'liq':>4}  state mix")
    windows = [("2020-01-01", "full"), ("2021-11-01", "last-top"), ("2023-01-01", "post-bear")]
    for wstart, wlabel in windows:
        w0 = pd.Timestamp(wstart, tz="UTC")
        px = btc.loc[w0:end]
        print(f"--- window {wlabel}: {px.index[0].date()} -> {px.index[-1].date()} "
              f"({len(px)}d, BTC {px['close'].iloc[0]:,.0f} -> {px['close'].iloc[-1]:,.0f}) ---")
        bh = (1 + px["close"].pct_change().fillna(0)).cumprod() * START_CASH
        f0, c0, d0 = stats(bh, px.index[0], px.index[-1])
        print(f"{'spot buy&hold':16} {f0:>12,.0f} {c0:>+6.1f}% {d0:>6.1f}%")
        arms = [("jev_full_daily", px, tgt_d.reindex(px.index), funding.loc[w0:end], 2.0),
                ("jev_weekly", px, tgt_w.reindex(px.index), funding.loc[w0:end], 2.0)]
        pxw = px4.loc[w0:end]
        arms.append(("jev_4h", pxw, tgt_4.reindex(pxw.index), fund_4.reindex(pxw.index), 2.0))
        for name, pxx, tgt, fnd, cap in arms:
            eq, s = sim_signed(pxx, tgt.fillna(0.0), cap, fnd)
            if float(eq.iloc[-1]) == 0.0 and s["liq"]:
                print(f"{name:16} {'LIQUIDATED':>12}  first {s['liq'][0]}")
                continue
            f1, c1, d1 = stats(eq, pxx.index[0], pxx.index[-1])
            n = len(pxx)
            mix = (f"2x={(tgt == 2).mean() * 100:.0f}% 1x={(tgt == 1).mean() * 100:.0f}% "
                   f"cash={(tgt == 0).mean() * 100:.0f}% sh={(tgt == -1).mean() * 100:.0f}%")
            wtxt = f" wick {s['worst_wick']:.2f}x" if s["worst_wick"] else ""
            print(f"{name:16} {f1:>12,.0f} {c1:>+6.1f}% {d1:>6.1f}% "
                  f"{s['flips']:>7} {s['entries']:>7} {s['funding_total']:>10,.0f} "
                  f"{len(s['liq']):>4}  {mix}{wtxt}")
        # churn proof: flips per year by cadence
        yrs = len(px) / 365.25
        fd = tgt_d.reindex(px.index).fillna(0.0)
        fw = tgt_w.reindex(px.index).fillna(0.0)
        f4 = tgt_4.reindex(pxw.index).fillna(0.0)
        nd = int((fd.diff().abs() > 0).sum())
        nw = int((fw.diff().abs() > 0).sum())
        n4 = int((f4.diff().abs() > 0).sum())
        print(f"churn [{wlabel}]: target changes weekly={nw} ({nw / yrs:.1f}/yr) "
              f"daily={nd} ({nd / yrs:.1f}/yr) 4h-bar-changes={n4} ({n4 / yrs:.1f}/yr) "
              f"=> 4h/daily={n4 / max(nd, 1):.1f}x, daily/weekly={nd / max(nw, 1):.1f}x")

    print("\nStateless: results printed above, nothing saved.")


if __name__ == "__main__":
    main()
