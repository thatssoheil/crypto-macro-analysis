#!/usr/bin/env python3
"""
JEV-MULTITIMEFRAME prototype (stateless, stdout only).

Layer 0 - DAILY PERMISSION (improved heat gate, long-only direction):
  5 heat flags, all trailing / known at the close:
    f_fund  : daily funding rate strictly above trailing-365d 90th pct
    f_frothy: Fear&Greed > 75 AND close > 10% above 200d-MA
    f_vix   : VIX > 30
    f_vol   : BTC 7d realized vol strictly above trailing-180d 90th pct
    f_ext   : close > 50% above 200d-MA (drawdown-extension / blow-off)
  permitted = fewer than 2 flags fire (trade day unless 2 of 5).
  daily direction = 1 when close >= 200d-MA AND permitted, else cash.
  sizing: 2x only when funding < trailing-365d median AND close >= 200d-MA
          (and permitted), else 1x. Pre-2020 funding NaN -> gate fails safe.

Layer 1 - 4H BIAS (hourly aggregated to 4h bars, 00/04/.../20 UTC):
  raw = +1 when 4h-close 50-bar MA > 200-bar MA, -1 when below (0 in warmup).
  gated bias: LONG (+1) when raw > 0 AND daily direction == 1 (prior-day
              print: a same-day daily print is not known intraday);
              SHORT (-1) only when close < 200d-MA (prior day) AND prior-day
              funding < 0; else flat.
  raw bias (arm B only): pure 4h cross, both directions, no daily conditions.

Layer 2 - 1H ENTRY TIMING:
  position follows the 1h-mapped bias (4h bar close shifted +4h, ffilled to
  1h, then the house .shift(1): the bar earned is set at the prior close, so
  no 1h bar ever uses a 4h close that was not yet printed).
  Enter on 1h close in bias direction; exit when the 4h bias flips or on a
  2% adverse stop from entry (stop exits re-enter on the next 1h close if the
  bias is still on). Intraday leverage is 1x (sizing lives in Layer 0).

Four arms (per window, $10k restart):
  A daily-permission : Layer 0 alone (daily bars, 1x/2x tiered long / cash).
  B intraday-raw     : Layers 1-raw + 2, NO daily gate (pure 4h cross both ways).
  C intraday-gated   : Layers 1-gated + 2 (bias only on permitted days).
  D intraday-cheap   : arm C + longs only when funding < trailing median
                       (cheap-funding filter; shorts still need funding < 0).
  E bisect-sizing    : SAME L0 entries as A, but leverage from binary search:
                       start max 2x, each hot flag halves the interval down,
                       each cold flag keeps the upper half (severity order:
                       ext, fund, vol, vix, frothy), 0.25 steps; floored to
                       cash when permission denies. A-vs-E compares sizing
                       (trades / funding / maxDD) on identical entries.

Accounting (house conventions from futures_vs_spot.py):
  $10k start per window, cash 0%, isolated margin, notional = lev x equity at
  each (re)entry, mark-to-market on closes, LIQUIDATION at mm = 0.5% tested on
  bar low (long) / high (short); entry-bar wick never tested. Longs pay
  funding on open notional (shorts receive); daily rate split /24 per hour
  intraday (sums to the daily charge). No fees/slippage. Nothing saved.
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "macro_dataset"
MM = 0.005
START_CASH = 10000.0
STOP = 0.02


def load_daily_ohlc():
    df = pd.read_csv(DATA / "btcusd_daily_bitstamp.csv")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()[["open", "high", "low", "close"]]


def load_hourly():
    h = pd.read_csv(DATA / "btcusd_hourly_bitstamp.csv")
    h["ts"] = pd.to_datetime(h["ts"], utc=True)
    return h.set_index("ts").sort_index()[["open", "high", "low", "close"]]


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
    f_vol = (rv7 > rv_q90).fillna(False)
    f_ext = ext50

    nflags = (f_fund.astype(int) + f_frothy.astype(int) + f_vix.astype(int)
              + f_vol.astype(int) + f_ext.astype(int))
    permitted = nflags < 2
    direction = (above & permitted).astype(float)
    lev = pd.Series(0.0, index=px.index)
    lev[direction >= 0.5] = 1.0
    lev[(direction >= 0.5) & fund_ok] = 2.0  # fund_ok implies data exists
    return pd.DataFrame({
        "ma200": ma200, "above": above, "fund": fund, "fund_ok": fund_ok,
        "f_fund": f_fund, "f_frothy": f_frothy, "f_vix": f_vix,
        "f_vol": f_vol, "f_ext": f_ext, "nflags": nflags,
        "permitted": permitted, "direction": direction, "lev": lev,
    })


def build_4h_bias(px4, dst):
    """Layer-1 bias on 4h bars. Daily state via prior-day prints (no lookahead)."""
    c4 = px4["close"]
    ma50 = c4.rolling(50).mean()
    ma200 = c4.rolling(200).mean()
    raw = pd.Series(0.0, index=px4.index)
    raw[ma50 > ma200] = 1.0
    raw[ma50 < ma200] = -1.0

    daykey = px4.index.floor("D") - pd.Timedelta(days=1)
    perm = pd.Series(dst["permitted"].reindex(daykey).to_numpy(),
                     index=px4.index).fillna(False).astype(bool)
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


def bisect_lev(dst):
    """Binary-search sizing from max 2x over the 5 heat flags.

    Interval [0, 2]: each hot flag keeps the lower half, each cold flag the
    upper half; flags ordered most-severe first (ext, fund, vol, vix,
    frothy). Converge to 0.25 steps. 0 hot -> 2.0; single-hot -> 2.0/1.75/
    1.5/1.0 by flag severity; permission denied -> floored to cash (0).
    Unlike tier sizing this ignores the funding-median gate for 2x.
    """
    order = ["f_ext", "f_fund", "f_vol", "f_vix", "f_frothy"]
    lev = pd.Series(0.0, index=dst.index)
    hot = {c: dst[c].to_numpy(bool) for c in order}
    perm = dst["permitted"].to_numpy(bool)
    dirc = dst["direction"].to_numpy(float)
    out = np.zeros(len(dst))
    for i in range(len(dst)):
        lo, hi = 0.0, 2.0
        for c in order:
            mid = (lo + hi) / 2.0
            if hot[c][i]:
                hi = mid
            else:
                lo = mid
        out[i] = round((lo + hi) / 2.0 * 4) / 4
    lev = pd.Series(out, index=dst.index)
    lev[~perm] = 0.0
    lev[dirc < 0.5] = 0.0
    return lev


def map_4h_to_1h(bias4, h1_index):
    """4h-bar close at label+4h is first known then; ffill from close time."""
    b = bias4.copy()
    b.index = b.index + pd.Timedelta(hours=4)
    return b.reindex(h1_index, method="ffill").fillna(0.0)


def map_daily_to_1h(dseries, h1_index, fill):
    key = h1_index.floor("D") - pd.Timedelta(days=1)
    return pd.Series(dseries.reindex(key).to_numpy(),
                     index=h1_index).fillna(fill)


def sim_daily(px, direction, lev_target, funding):
    """Long-only variable-lev daily loop + round-trip trade log."""
    close = px["close"].to_numpy(float)
    low = px["low"].to_numpy(float)
    dr, lv = direction.to_numpy(float), lev_target.to_numpy(float)
    fund = funding.reindex(px.index).fillna(0.0).to_numpy(float)
    n = len(close)
    cash, size, entry, entry_cash, cur_lev = START_CASH, 0.0, 0.0, 0.0, 0.0
    eqs = np.zeros(n)
    funding_total, switches, resizes = 0.0, 0, 0
    trades, wins, days_in = 0, 0, 0
    liq = []
    for i in range(n):
        if size != 0.0 and i > 0:
            prev_close = close[i - 1]
            equity_prev = cash + size * (prev_close - entry)
            liq_px = (size * prev_close - equity_prev) / (size * (1 - MM))
            if low[i] <= liq_px:
                liq.append(str(px.index[i].date()) + " long")
                pnl = cash - entry_cash  # total loss of the round trip
                trades += 1
                wins += int(pnl > 0)
                cash, size, cur_lev = 0.0, 0.0, 0.0
            else:
                cost = fund[i] * abs(size) * close[i]
                cash -= cost
                funding_total += cost
                days_in += 1
        if size == 0.0 and cash <= 0.0:
            eqs[i] = 0.0
            continue
        t_dir = 1.0 if dr[i] >= 0.5 else 0.0
        t_lev = float(lv[i]) if t_dir == 1.0 else 0.0
        if size != 0.0 and t_dir == 0.0:
            cash += size * (close[i] - entry)
            trades += 1
            wins += int(cash - entry_cash > 0)
            size, cur_lev = 0.0, 0.0
        elif size == 0.0 and t_dir != 0.0:
            size = cash * t_lev / close[i]
            entry, entry_cash, cur_lev = close[i], cash, t_lev
            switches += 1
        elif size != 0.0 and t_lev != cur_lev:
            cash += size * (close[i] - entry)
            size = cash * t_lev / close[i]
            entry, cur_lev = close[i], t_lev
            resizes += 1
        eqs[i] = cash + (size * (close[i] - entry) if size != 0.0 else 0.0)
    eq = pd.Series(eqs, index=px.index)
    return eq, {"trades": trades, "wins": wins, "funding_total": funding_total,
                "liq": liq, "switches": switches, "resizes": resizes,
                "bars_in": days_in, "bars_total": n}


def sim_intraday(h1, bias, fund_h, cheap_ok=None):
    """Signed 1x 1h loop: bias target, 2% stop, liq on wick, trade log.

    bias: raw (unshifted) 1h-mapped series; bar i is earned by target[i-1].
    cheap_ok: optional 1h boolean; long entries/continuation need it True.
    """
    close = h1["close"].to_numpy(float)
    low = h1["low"].to_numpy(float)
    high = h1["high"].to_numpy(float)
    st = bias.to_numpy(float)
    fh = fund_h.reindex(h1.index).fillna(0.0).to_numpy(float)
    co = (None if cheap_ok is None
          else cheap_ok.reindex(h1.index).fillna(False).to_numpy(bool))
    n = len(close)
    cash, size, entry, entry_cash, cur = START_CASH, 0.0, 0.0, 0.0, 0.0
    eqs = np.zeros(n)
    funding_total, entries = 0.0, 0
    trades, wins, bars_in = 0, 0, 0
    liq, stops = [], 0

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
                    liq.append(str(h1.index[i]) + " long")
                    close_trade(cash - entry_cash)
                    cash, size, cur = 0.0, 0.0, 0.0
                elif low[i] <= entry * (1 - STOP):
                    sp = entry * (1 - STOP)
                    cash += size * (sp - entry)
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
                    liq.append(str(h1.index[i]) + " short")
                    close_trade(cash - entry_cash)
                    cash, size, cur = 0.0, 0.0, 0.0
                elif high[i] >= entry * (1 + STOP):
                    sp = entry * (1 + STOP)
                    cash += size * (sp - entry)
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
        want = float(st[i])
        want = 1.0 if want >= 0.5 else (-1.0 if want <= -0.5 else 0.0)
        if co is not None and want > 0 and not bool(co[i]):
            want = 0.0
        if want != cur:
            if size != 0.0:
                cash += size * (close[i] - entry)
                close_trade(cash - entry_cash)
                size = 0.0
            if want != 0.0 and cash > 0.0:
                size = np.sign(want) * cash * 1.0 / close[i]
                entry, entry_cash = close[i], cash
                entries += 1
            cur = want if (size != 0.0 or want == 0.0) else 0.0
        eqs[i] = cash + (size * (close[i] - entry) if size != 0.0 else 0.0)
    eq = pd.Series(eqs, index=h1.index)
    return eq, {"trades": trades, "wins": wins, "funding_total": funding_total,
                "liq": liq, "stops": stops, "entries": entries,
                "bars_in": bars_in, "bars_total": n}


def stats(eq, start_cash=START_CASH):
    final = float(eq.iloc[-1])
    yrs = max((eq.index[-1] - eq.index[0]).total_seconds() / 31557600.0, 1e-9)
    cagr = ((final / start_cash) ** (1 / yrs) - 1) * 100 if final > 0 else -100.0
    dd = float((eq / eq.cummax() - 1).min() * 100)
    return final, cagr, dd, yrs


def main():
    btc = load_daily_ohlc()
    h1 = load_hourly()
    funding = load_series("bn_funding_btc")
    vix = load_series("vix", "close")
    fng = load_series("fear_greed")
    end = min(btc.index.max(), funding.index.max(), h1.index.max())
    print("=== JEV-MULTITIMEFRAME: daily permission x 4h bias x 1h timing ===")
    print(f"through {end.date()} | daily {len(btc)} rows | hourly {len(h1)} rows | "
          f"funding {funding.index.min().date()}..{funding.index.max().date()}")
    print("L0: permitted = <2 of 5 heat flags (fund-p90-365d, F&G>75&+10%MA200, "
          "VIX>30, rv7-p90-180d, +50%MA200); 2x only if fund<median & >=MA200.")
    print("L1: 4h bias long = 4hMA50>MA200 AND daily-dir (prior day); short only "
          "if <MA200 & funding<0. L2: 1h close entries, 4h-flip exit, 2% stop.")
    print("No lookahead: daily state at close d earns d+1; 4h uses prior-day "
          "daily prints; 1h uses 4h closes known >=4h earlier; mm=0.5%, $10k/window.")

    dst = build_daily(btc, funding, vix, fng)
    px4 = to_4h(h1)
    raw4, gated4 = build_4h_bias(px4, dst)
    bias_raw_1h = map_4h_to_1h(raw4, h1.index)
    bias_gated_1h = map_4h_to_1h(gated4, h1.index)
    fundok_1h = map_daily_to_1h(dst["fund_ok"], h1.index, False)

    # sanity: gated longs are a subset of raw longs (permission only removes)
    assert int(((gated4 > 0) & ~(raw4 > 0)).sum()) == 0
    assert int(((gated4 < 0) & ~(raw4 < 0)).sum()) == 0

    windows = [("2020-01-01", "2020+ funding era"),
               ("2021-11-01", "2021-11 top+"),
               ("2023-01-01", "2023+ post-bear")]
    for wstart, wlabel in windows:
        w0 = pd.Timestamp(wstart, tz="UTC")
        px = btc.loc[w0:end]
        hh = h1.loc[w0:end]
        d = dst.loc[w0:end]
        fd = funding.loc[w0:end]
        br = bias_raw_1h.loc[w0:end]
        bg = bias_gated_1h.loc[w0:end]
        fo = fundok_1h.loc[w0:end]
        fh = map_daily_to_1h(dst["fund"].loc[w0:end], hh.index, 0.0) / 24.0

        arms = []
        eq, s = sim_daily(px, d["direction"], d["lev"], fd)
        s["flips"] = int((d["direction"].diff().abs() > 0).sum())
        arms.append(("A daily-permission (L0)", eq, s, len(px), "d"))
        eq, s = sim_intraday(hh, br, fh)
        s["flips"] = int((br.diff().abs() > 0).sum())
        arms.append(("B intraday-raw (no gate)", eq, s, len(hh), "h"))
        eq, s = sim_intraday(hh, bg, fh)
        s["flips"] = int((bg.diff().abs() > 0).sum())
        arms.append(("C intraday-gated (L0+L1+L2)", eq, s, len(hh), "h"))
        eq, s = sim_intraday(hh, bg, fh, cheap_ok=fo)
        s["flips"] = int((bg.diff().abs() > 0).sum())
        arms.append(("D gated + cheap-fund", eq, s, len(hh), "h"))
        eq, s = sim_daily(px, d["direction"], bisect_lev(dst).loc[w0:end], fd)
        s["flips"] = int((d["direction"].diff().abs() > 0).sum())
        arms.append(("E bisect-sizing (L0 entries)", eq, s, len(px), "d"))

        print(f"\n=== window {wlabel}: {px.index[0].date()} -> {px.index[-1].date()} "
              f"({len(px)}d / {len(hh)}h, BTC {px['close'].iloc[0]:,.0f} -> "
              f"{px['close'].iloc[-1]:,.0f}) ===")
        bh = (1 + px["close"].pct_change().fillna(0)).cumprod() * START_CASH
        f0, c0, dd0, _ = stats(bh)
        print(f"ref spot buy&hold: final ${f0:,.0f} CAGR {c0:+.1f}% maxDD {dd0:.1f}%")
        print(f"{'arm':26} {'final $':>10} {'CAGR':>7} {'maxDD':>7} "
              f"{'trades':>6} {'win%':>5} {'fund $':>9} {'in-mkt':>6} "
              f"{'flips':>6} {'liq':>3}")
        for name, eq, s, nbars, unit in arms:
            if float(eq.iloc[-1]) == 0.0 and s["liq"]:
                print(f"{name:26} LIQUIDATED first {s['liq'][0]}")
                continue
            final, cagr, dd, yrs = stats(eq)
            tr, wn = s["trades"], s["wins"]
            wtxt = f"{wn / tr * 100:>4.0f}%" if tr else "  n/a"
            print(f"{name:26} {final:>10,.0f} {cagr:>+6.1f}% {dd:>6.1f}% "
                  f"{tr:>6} {wtxt} {s['funding_total']:>9,.0f} "
                  f"{s['bars_in'] / nbars * 100:>5.1f}% {s['flips']:>6} "
                  f"{len(s['liq']):>3}")

        r = d["nflags"]
        print(f"L0 days: permitted={int(d['permitted'].sum())}/{len(d)} "
              f"({d['permitted'].mean() * 100:.0f}%) vetoed(2+ flags)={int((~d['permitted']).sum())} | "
              f"flags: fund={int(d['f_fund'].sum())} frothy={int(d['f_frothy'].sum())} "
              f"vix={int(d['f_vix'].sum())} vol={int(d['f_vol'].sum())} ext50={int(d['f_ext'].sum())} | "
              f"2x-days={(d['lev'] == 2).sum()} 1x-days={(d['lev'] == 1).sum()}")
        yrs = len(px) / 365.25
        tA, tB, tC = arms[0][2]["trades"], arms[1][2]["trades"], arms[2][2]["trades"]
        print(f"churn: trades/yr A={tA / yrs:.1f} B={tB / yrs:.1f} "
              f"C={tC / yrs:.1f} (C/B={tC / max(tB, 1):.2f}x) | "
              f"bias flips: raw={arms[1][2]['flips']} gated={arms[2][2]['flips']} | "
              f"stops B={arms[1][2].get('stops', 0)} C={arms[2][2].get('stops', 0)} "
              f"D={arms[3][2].get('stops', 0)}")
        # bisect (E) vs fixed-tier (A) sizing on identical L0 entries
        sA, sE = arms[0][2], arms[4][2]
        _, _, ddA, _ = stats(arms[0][1])
        _, _, ddE, _ = stats(arms[4][1])
        mix = bisect_lev(dst).loc[w0:end]
        print(f"sizing A-vs-E (same entries): trades A={sA['trades']} E={sE['trades']} | "
              f"funding A=${sA['funding_total']:,.0f} E=${sE['funding_total']:,.0f} | "
              f"maxDD A={ddA:.1f}% E={ddE:.1f}% | "
              f"E lev mix: " + " ".join(
                  f"{v:g}x={(mix[d['direction'] >= 0.5] == v).sum()}"
                  for v in sorted(mix.unique())))

    print("\nStateless: results printed above, nothing saved.")


if __name__ == "__main__":
    main()
