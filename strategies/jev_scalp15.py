#!/usr/bin/env python3
"""JEV-SCALP15 prototype (stateless, stdout only).

Layer 0 - DAILY PERMISSION (from jev_multitimeframe, unchanged):
  5 heat flags, all trailing / known at the close:
    f_fund  : daily funding strictly above trailing-365d 90th pct
    f_frothy: Fear&Greed > 75 AND close > 10% above 200d-MA
    f_vix   : VIX > 30
    f_vol   : BTC 7d realized vol strictly above trailing-180d 90th pct
    f_ext   : close > 50% above 200d-MA
  permitted = fewer than 2 flags fire. Veto days -> leverage zero (flat).
  daily direction = 1 when close >= 200d-MA AND permitted, else cash.

Layer 1 - 4H BIAS (hourly aggregated to 4h bars, 00/04/.../20 UTC):
  raw = +1 when 4h-close 50-bar MA > 200-bar MA, -1 when below (0 warmup).
  gated: LONG only when raw > 0 AND prior-day daily direction == 1;
         SHORT only when raw < 0 AND prior-day close < 200d-MA
         AND prior-day funding < 0; else flat.

Layer 2 - 15M TIMING:
  4h bias mapped to 15m (4h close first known at label+4h, ffill), then
  .shift(1): the bar earned is set at the prior close. Enter on 15m close
  in bias direction; exit on bias flip / veto day / stop.

Sizing (per 15m entry, isolated margin):
  bisect lev: interval [0,10], each hot flag keeps lower half, each cold
    flag keeps upper half, severity order ext/fund/vol/vix/frothy,
    rounded to 0.25 steps; 0 on veto days. Max 10x.
  risk cap: notional = risk_frac * equity / stop_dist, i.e. lev <= risk/stop.
    risk = 1% calm; 2% only when prior-day funding < trailing-365d median
    AND 7d vol calm (rv7 <= trailing-180d median).
    stop = 0.5% base, tightened to 0.3% when rv7 in trailing-180d top decile.
  effective lev = min(bisect, risk/stop, 10), floored to 0.25 steps.

Arms (per window, $10k restart):
  A fixed-2x       : lev 2.0 on every gated entry (risk cap off).
  B bisect-risk1%  : lev = min(bisect[0,10], 0.01/stop).
  C bisect-risk1-2%: lev = min(bisect[0,10], risk/stop), risk 1-2% as above.

Accounting (house rules): $10k start, cash 0%, notional = lev x equity at
each entry, mark-to-market on 15m closes, LIQUIDATION at mm = 0.5% tested on
bar wick (long: low, short: high; entry bar never tested), 5bp fee per side
on notional at entry AND exit, funding on notional per bar (daily rate / 96;
longs pay, shorts receive). Nothing saved.
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "macro_dataset"
MM = 0.005
START_CASH = 10000.0
FEE = 0.0005
STOP_BASE = 0.005
STOP_TIGHT = 0.003
MAX_LEV = 10.0
FLAG_ORDER = ["f_ext", "f_fund", "f_vol", "f_vix", "f_frothy"]


def load_daily_ohlc():
    df = pd.read_csv(DATA / "btcusd_daily_bitstamp.csv")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()[["open", "high", "low", "close"]]


def load_hourly():
    h = pd.read_csv(DATA / "btcusd_hourly_bitstamp.csv")
    h["ts"] = pd.to_datetime(h["ts"], utc=True)
    return h.set_index("ts").sort_index()[["open", "high", "low", "close"]]


def load_15m():
    px = pd.read_csv(DATA / "btc_15m_binance.csv")
    px["ts"] = pd.to_datetime(px["open_time"], unit="ms", utc=True)
    return px.set_index("ts").sort_index()[["open", "high", "low", "close", "volume"]]


def load_series(name, col="value"):
    df = pd.read_csv(DATA / f"{name}.csv")
    dc = "date" if "date" in df.columns else "ts"
    df[dc] = pd.to_datetime(df[dc], utc=True)
    return df.set_index(dc).sort_index()[col]


def to_4h(h):
    grp = h.index.floor("4h")
    px = pd.DataFrame({
        "open": h["open"].groupby(grp).first(),
        "high": h["high"].groupby(grp).max(),
        "low": h["low"].groupby(grp).min(),
        "close": h["close"].groupby(grp).last(),
    })
    px.index.name = "ts"
    return px


def build_daily(px, funding, vix, fng):
    """Full-history Layer-0 state. All trailing / known-at-close."""
    close = px["close"]
    ma200 = close.rolling(200).mean()
    above = (close >= ma200).fillna(False)
    ext10 = (close > 1.10 * ma200).fillna(False)
    ext50 = (close > 1.50 * ma200).fillna(False)

    fund = funding.reindex(px.index)
    q90 = fund.rolling(365, min_periods=30).quantile(0.9)
    f_fund = (fund > q90).fillna(False)
    fmed = fund.rolling(365, min_periods=30).median()
    fund_ok = (fund < fmed).fillna(False)

    vx = vix.reindex(px.index).ffill()
    fg = fng.reindex(px.index).ffill()
    f_frothy = ((fg > 75) & ext10).fillna(False)
    f_vix = (vx > 30).fillna(False)

    lret = np.log(close / close.shift(1))
    rv7 = lret.rolling(7).std()
    rv_q90 = rv7.rolling(180, min_periods=30).quantile(0.9)
    rv_med = rv7.rolling(180, min_periods=30).median()
    f_vol = (rv7 > rv_q90).fillna(False)
    vol_calm = (rv7 <= rv_med).fillna(False)
    stop_tight = (rv7 > rv_q90).fillna(False)
    f_ext = ext50

    nflags = (f_fund.astype(int) + f_frothy.astype(int) + f_vix.astype(int)
              + f_vol.astype(int) + f_ext.astype(int))
    permitted = nflags < 2
    direction = (above & permitted).astype(float)
    risk2 = (fund_ok & vol_calm)
    return pd.DataFrame({
        "ma200": ma200, "above": above, "fund": fund, "fund_ok": fund_ok,
        "f_fund": f_fund, "f_frothy": f_frothy, "f_vix": f_vix,
        "f_vol": f_vol, "f_ext": f_ext, "nflags": nflags,
        "permitted": permitted, "direction": direction,
        "risk2": risk2, "stop_tight": stop_tight, "rv7": rv7,
    })


def bisect_lev_10(dst):
    """Binary-search sizing from max 10x over the 5 heat flags, 0.25 steps."""
    out = np.zeros(len(dst))
    hot = {c: dst[c].to_numpy(bool) for c in FLAG_ORDER}
    for i in range(len(dst)):
        lo, hi = 0.0, MAX_LEV
        for c in FLAG_ORDER:
            mid = (lo + hi) / 2.0
            if hot[c][i]:
                hi = mid
            else:
                lo = mid
        out[i] = np.floor((lo + hi) / 2.0 * 4) / 4
    lev = pd.Series(out, index=dst.index)
    lev[~dst["permitted"].to_numpy(bool)] = 0.0
    return lev


def build_4h_bias(px4, dst):
    """Layer-1 bias on 4h bars. Daily state via prior-day prints."""
    c4 = px4["close"]
    ma50 = c4.rolling(50).mean()
    ma200 = c4.rolling(200).mean()
    raw = pd.Series(0.0, index=px4.index)
    raw[ma50 > ma200] = 1.0
    raw[ma50 < ma200] = -1.0

    daykey = px4.index.floor("D") - pd.Timedelta(days=1)
    ddir = pd.Series(dst["direction"].reindex(daykey).to_numpy(),
                     index=px4.index).fillna(0.0).to_numpy()
    above = pd.Series(dst["above"].reindex(daykey).to_numpy(),
                      index=px4.index).fillna(False).astype(bool).to_numpy()
    fund = pd.Series(dst["fund"].reindex(daykey).to_numpy(),
                     index=px4.index).fillna(0.0).to_numpy()

    gated = pd.Series(0.0, index=px4.index)
    gated[(raw > 0).to_numpy() & (ddir >= 0.5)] = 1.0
    gated[(raw < 0).to_numpy() & (~above) & (fund < 0)] = -1.0
    return raw, gated


def map_4h_to_15m(bias4, idx15):
    """4h-bar close at label+4h is first known then; ffill from close time."""
    b = bias4.copy()
    b.index = b.index + pd.Timedelta(hours=4)
    return b.reindex(idx15, method="ffill").fillna(0.0)


def map_daily_to_15m(dseries, idx15, fill):
    key = idx15.floor("D") - pd.Timedelta(days=1)
    return pd.Series(dseries.reindex(key).to_numpy(),
                     index=idx15).fillna(fill)


def sim_scalp(px15, want, lev_in, stop_in, fund_h):
    """Signed variable-lev 15m loop: bias target, stop, liq on wick, fees.

    want/lev_in/stop_in: raw (unshifted) 15m-mapped series; bar i is earned
    by target[i-1]. want in {-1,0,+1}; lev 0 forces flat (veto).
    """
    close = px15["close"].to_numpy(float)
    low = px15["low"].to_numpy(float)
    high = px15["high"].to_numpy(float)
    st = want.to_numpy(float)
    lv = lev_in.to_numpy(float)
    sd = stop_in.to_numpy(float)
    fh = fund_h.reindex(px15.index).fillna(0.0).to_numpy(float)
    n = len(close)
    cash, size, entry, entry_cash, entry_lev, entry_sd, cur = \
        START_CASH, 0.0, 0.0, 0.0, 0.0, STOP_BASE, 0.0
    eqs = np.zeros(n)
    funding_total, fee_total, entries = 0.0, 0.0, 0
    trades, wins, stops, bars_in = 0, 0, 0, 0
    liq = []
    lev_mix = {}

    def close_trade(pnl):
        nonlocal trades, wins
        trades += 1
        wins += int(pnl > 0)

    for i in range(n):
        if size != 0.0 and i > 0:
            prev_close = close[i - 1]
            equity_prev = cash + size * (prev_close - entry)
            if size > 0:
                liq_px = (size * prev_close - equity_prev) / (size * (1 - MM))
                if low[i] <= liq_px:
                    liq.append(str(px15.index[i]) + " long")
                    close_trade(cash - entry_cash)
                    cash, size, cur = 0.0, 0.0, 0.0
                elif low[i] <= entry * (1 - entry_sd):
                    sp = entry * (1 - entry_sd)
                    cash += size * (sp - entry)
                    cash -= FEE * abs(size) * sp
                    fee_total += FEE * abs(size) * sp
                    close_trade(cash - entry_cash)
                    size, cur = 0.0, 0.0
                    stops += 1
                else:
                    cost = fh[i] * abs(size) * close[i]
                    cash -= cost
                    funding_total += cost
                    bars_in += 1
            else:
                liq_px = (equity_prev - size * prev_close) / (-size * (1 + MM))
                if high[i] >= liq_px:
                    liq.append(str(px15.index[i]) + " short")
                    close_trade(cash - entry_cash)
                    cash, size, cur = 0.0, 0.0, 0.0
                elif high[i] >= entry * (1 + entry_sd):
                    sp = entry * (1 + entry_sd)
                    cash += size * (sp - entry)
                    cash -= FEE * abs(size) * sp
                    fee_total += FEE * abs(size) * sp
                    close_trade(cash - entry_cash)
                    size, cur = 0.0, 0.0
                    stops += 1
                else:
                    cost = -fh[i] * abs(size) * close[i]  # shorts receive
                    cash -= cost
                    funding_total += cost
                    bars_in += 1
        if size == 0.0 and cash <= 0.0:
            eqs[i] = 0.0
            continue
        tgt = float(st[i - 1]) if i > 0 else 0.0
        tgt = 1.0 if tgt >= 0.5 else (-1.0 if tgt <= -0.5 else 0.0)
        t_lev = float(lv[i - 1]) if i > 0 else 0.0
        t_sd = float(sd[i - 1]) if i > 0 else STOP_BASE
        if t_lev <= 0.0:
            tgt = 0.0
        if tgt != cur or (tgt != 0.0 and t_lev != entry_lev):
            if size != 0.0:
                cash += size * (close[i] - entry)
                fee = FEE * abs(size) * close[i]
                cash -= fee
                fee_total += fee
                close_trade(cash - entry_cash)
                size = 0.0
            if tgt != 0.0 and cash > 0.0:
                size = np.sign(tgt) * cash * t_lev / close[i]
                fee = FEE * abs(size) * close[i]
                cash -= fee
                fee_total += fee
                entry, entry_cash = close[i], cash
                entry_lev, entry_sd = t_lev, t_sd
                entries += 1
                lev_mix[round(t_lev, 2)] = lev_mix.get(round(t_lev, 2), 0) + 1
            cur = tgt if size != 0.0 else 0.0
        eqs[i] = cash + (size * (close[i] - entry) if size != 0.0 else 0.0)
    eq = pd.Series(eqs, index=px15.index)
    return eq, {"trades": trades, "wins": wins, "stops": stops,
                "funding_total": funding_total, "fee_total": fee_total,
                "liq": liq, "entries": entries, "bars_in": bars_in,
                "bars_total": n, "lev_mix": lev_mix}


def stats(eq, start_cash=START_CASH):
    final = float(eq.iloc[-1])
    yrs = max((eq.index[-1] - eq.index[0]).total_seconds() / 31557600.0, 1e-9)
    cagr = ((final / start_cash) ** (1 / yrs) - 1) * 100 if final > 0 else -100.0
    dd = float((eq / eq.cummax() - 1).min() * 100)
    return final, cagr, dd, yrs


def main():
    btc = load_daily_ohlc()
    h1 = load_hourly()
    px15 = load_15m()
    funding = load_series("bn_funding_btc")
    vix = load_series("vix", "close")
    fng = load_series("fear_greed")
    end = min(btc.index.max(), funding.index.max(), h1.index.max(), px15.index.max())
    print("=== JEV-SCALP15: daily permission x 4h bias x 15m timing ===")
    print(f"through {end} | daily {len(btc)} rows | hourly {len(h1)} rows | "
          f"15m {len(px15)} rows ({px15.index[0]} -> {px15.index[-1]}) | "
          f"funding {funding.index.min().date()}..{funding.index.max().date()}")
    print("L0: permitted = <2 of 5 heat flags (fund-p90-365d, F&G>75&+10%MA200, "
          "VIX>30, rv7-p90-180d, +50%MA200); veto days flat (lev 0).")
    print("L1: 4h bias (hourly->4h MA50/MA200) long needs prior-day L0 dir; "
          "short needs prior-day <MA200 & funding<0. L2: 15m-close entries.")
    print("Sizing: bisect [0,10] per hot flag (ext/fund/vol/vix/frothy, 0.25 "
          "steps) capped by risk/stop (risk 1%, 2% iff fund<median & vol calm; "
          "stop 0.5%, 0.3% if rv7 top-decile). Arms: A fixed-2x, B bisect+1%, "
          "C bisect+1-2%. Fee 5bp/side, funding on notional, mm=0.5%, $10k.")
    print("No lookahead: daily prints earn d+1; 4h closes known +4h; 15m bar "
          "earned at prior close (.shift(1)).")

    dst = build_daily(btc, funding, vix, fng)
    px4 = to_4h(h1)
    raw4, gated4 = build_4h_bias(px4, dst)
    assert int(((gated4 > 0) & ~(raw4 > 0)).sum()) == 0
    assert int(((gated4 < 0) & ~(raw4 < 0)).sum()) == 0

    bias15 = map_4h_to_15m(gated4, px15.index)
    bis10 = bisect_lev_10(dst)
    bis15 = map_daily_to_15m(bis10, px15.index, 0.0)
    risk2_15 = map_daily_to_15m(dst["risk2"], px15.index, False).to_numpy(bool)
    tight15 = map_daily_to_15m(dst["stop_tight"], px15.index, False).to_numpy(bool)
    stop15 = pd.Series(np.where(tight15, STOP_TIGHT, STOP_BASE), index=px15.index)
    fund15 = map_daily_to_15m(dst["fund"], px15.index, 0.0) / 96.0
    risk_frac = np.where(risk2_15, 0.02, 0.01)

    levA = pd.Series(2.0, index=px15.index)
    levA[bis15 <= 0.0] = 0.0  # veto days flat in every arm
    capB = np.floor((0.01 / stop15.to_numpy(float)) * 4) / 4
    levB = pd.Series(np.minimum(bis15.to_numpy(float), capB), index=px15.index)
    capC = np.floor((risk_frac / stop15.to_numpy(float)) * 4) / 4
    levC = pd.Series(np.minimum(bis15.to_numpy(float), capC), index=px15.index)

    windows = [("2020-01-01", "2020+ funding era"),
               ("2021-11-01", "2021-11 top+"),
               ("2023-01-01", "2023+ post-bear")]
    for wstart, wlabel in windows:
        w0 = pd.Timestamp(wstart, tz="UTC")
        px = px15.loc[w0:end]
        bw = bias15.loc[w0:end]
        fhw = fund15.loc[w0:end]
        arms = []
        for nm, lv in [("A fixed-2x", levA.loc[w0:end]),
                       ("B bisect-10x risk1%", levB.loc[w0:end]),
                       ("C bisect-10x risk1-2%", levC.loc[w0:end])]:
            eq, s = sim_scalp(px, bw, lv, stop15.loc[w0:end], fhw)
            s["flips"] = int((bw.diff().abs() > 0).sum())
            arms.append((nm, eq, s))
        pxd = btc.loc[w0:end]
        print(f"\n=== window {wlabel}: {px.index[0]} -> {px.index[-1]} "
              f"({len(px)} 15m bars, BTC {px['close'].iloc[0]:,.0f} -> "
              f"{px['close'].iloc[-1]:,.0f}) ===")
        bh = (1 + pxd["close"].pct_change().fillna(0)).cumprod() * START_CASH
        f0, c0, dd0, _ = stats(bh)
        print(f"ref spot buy&hold: final ${f0:,.0f} CAGR {c0:+.1f}% maxDD {dd0:.1f}%")
        print(f"{'arm':22} {'final $':>10} {'CAGR':>7} {'maxDD':>7} "
              f"{'trades':>6} {'win%':>5} {'stop%':>5} {'fee $':>8} "
              f"{'fund $':>8} {'in-mkt':>6} {'liq':>3}")
        for name, eq, s in arms:
            if float(eq.iloc[-1]) == 0.0 and s["liq"]:
                print(f"{name:22} LIQUIDATED first {s['liq'][0]}")
                continue
            final, cagr, dd, yrs = stats(eq)
            tr, wn, stp = s["trades"], s["wins"], s["stops"]
            wtxt = f"{wn / tr * 100:>4.0f}%" if tr else "  n/a"
            stxt = f"{stp / tr * 100:>4.0f}%" if tr else "  n/a"
            print(f"{name:22} {final:>10,.0f} {cagr:>+6.1f}% {dd:>6.1f}% "
                  f"{tr:>6} {wtxt} {stxt} {s['fee_total']:>8,.0f} "
                  f"{s['funding_total']:>+8,.0f} "
                  f"{s['bars_in'] / s['bars_total'] * 100:>5.1f}% "
                  f"{len(s['liq']):>3}")
        for name, eq, s in arms:
            mix = s["lev_mix"]
            hist = " ".join(f"{k:g}x={v}" for k, v in sorted(mix.items()))
            r2days = int(dst.loc[w0:end][
                (dst.loc[w0:end]["risk2"]) & (dst.loc[w0:end]["permitted"])].shape[0])
            print(f"lev mix {name}: {hist if hist else '(no entries)'} | "
                  f"risk2-days={r2days} flips={s['flips']} entries={s['entries']}")

    print("\nStateless: results printed above, nothing saved.")


if __name__ == "__main__":
    main()
