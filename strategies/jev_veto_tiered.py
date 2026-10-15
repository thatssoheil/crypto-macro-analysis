#!/usr/bin/env python3
"""
JEV-AS-RISK-GATE STUDY - Jev-style composite as a RISK GATE (not a signal).

Two arms share the 200d-MA direction (the validated edge); the Jev-style risk
score only ever trims exposure, never creates it:
  VETO   : long 1x when close >= 200d-MA AND risk <= 0.7, else cash.
  TIERED : same direction; leverage from risk: <0.3 -> 2x, 0.3-0.7 -> 1x,
           >0.7 -> cash. The 2x leg is additionally gated on BTC above its
           200d-MA AND funding below its trailing-365d median (gate fail -> 1x).

risk = mean of 3 binary flags, all evaluated on data known at the close:
  f_fund : daily funding rate strictly above its trailing-365d 90th percentile
  f_heat : VIX > 30 OR (Fear&Greed > 75 AND BTC > 10% above its 200d-MA)
  f_vol  : BTC 7d realized vol (std of log returns) strictly above its
           trailing-180d 90th percentile

Since risk takes values {0, 1/3, 2/3, 1}: risk > 0.7 means ALL THREE flags
fire; risk < 0.3 means none fire.

Method (house conventions, see AGENTS.md + futures_vs_spot.py):
  - Price: Bitstamp BTC daily OHLC. Funding: bn_funding_btc.csv daily sums.
  - No lookahead: state known at close d earns day d+1 (same loop as
    futures_vs_spot.py: mark day i on the position set at close[i-1], then
    set the new position at close[i]).
  - Futures accounting: all capital posted as isolated margin; set-and-forget
    within a leverage tier (TIERED resizes only when the target tier changes,
    at the close, realizing into cash and re-entering at the same price).
    Liquidation vs funding-drifted equity, mm = 0.5%, tested on daily low
    (long) / high (short); entry-day wick never tested (position set at the
    close is first tested on the NEXT day's wick). Longs pay funding on open
    notional; cash earns 0%. $10k start per window.
  - Signals computed on FULL history, then sliced per window (trailing
    windows never peek). Stateless: prints to stdout, saves nothing.
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "macro_dataset"
MM = 0.005  # maintenance margin rate, same as futures_vs_spot.py


def load(name, date_col="date", col="close"):
    df = pd.read_csv(DATA / f"{name}.csv")
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    return df.set_index(date_col).sort_index()[col]


def load_ohlc():
    df = pd.read_csv(DATA / "btcusd_daily_bitstamp.csv")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()[["open", "high", "low", "close"]]


def build_risk(px):
    """Full-history risk flags + MA direction. All trailing/known-at-close."""
    close = px["close"]
    ma200 = close.rolling(200).mean()
    above = close >= ma200
    ext10 = close > 1.10 * ma200

    fund = load("bn_funding_btc", col="value").reindex(px.index)  # NaN pre-2020
    q90 = fund.rolling(365, min_periods=30).quantile(0.9)
    f_fund = (fund > q90).fillna(False)
    fmed = fund.rolling(365, min_periods=30).median()
    fund_ok = (fund < fmed).fillna(False)  # pre-2020: no data -> gate fails safe

    vix = load("vix").reindex(px.index).ffill()
    fng = load("fear_greed", col="value").reindex(px.index).ffill()
    f_heat = ((vix > 30) | ((fng > 75) & ext10)).fillna(False)

    lret = np.log(close / close.shift(1))
    rv7 = lret.rolling(7).std()
    rv_q90 = rv7.rolling(180, min_periods=30).quantile(0.9)
    f_vol = (rv7 > rv_q90).fillna(False)

    risk = (f_fund.astype(float) + f_heat.astype(float) + f_vol.astype(float)) / 3.0
    return pd.DataFrame({
        "ma200": ma200, "above": above, "ext10": ext10,
        "f_fund": f_fund, "f_heat": f_heat, "f_vol": f_vol,
        "risk": risk, "fund_ok": fund_ok,
    })


def sim_switchable(px, direction, lev_target, funding, start_cash=10000.0):
    """Variable-leverage futures loop. direction/lev_target: raw (unshifted)
    daily series; position earning day i is set at close[i-1]. LEV only
    applies when direction == 1 (else flat). Returns (equity, stats)."""
    close = px["close"].to_numpy(float)
    low = px["low"].to_numpy(float)
    high = px["high"].to_numpy(float)
    dr = direction.to_numpy(float)
    lv = lev_target.to_numpy(float)
    fund = funding.reindex(px.index).fillna(0.0).to_numpy(float)
    n = len(close)

    cash, size, entry, cur_lev = start_cash, 0.0, 0.0, 0.0
    eqs = np.zeros(n)
    funding_total, switches, resizes = 0.0, 0, 0
    liq_events, worst_wick = [], np.inf
    days_long, days_1x, days_2x = 0, 0, 0

    for i in range(n):
        # step 1: mark day i on the position held from close[i-1]
        if size != 0.0 and i > 0:
            prev_close = close[i - 1]
            equity_prev = cash + size * (prev_close - entry)
            liq_px = (size * prev_close - equity_prev) / (size * (1 - MM))
            if low[i] <= liq_px:
                liq_events.append(str(px.index[i].date()) + " long")
                cash, size, cur_lev = 0.0, 0.0, 0.0
            else:
                if liq_px > 0:  # flat/deep-ITM days put liq_px at/below zero: no wick risk
                    worst_wick = min(worst_wick, low[i] / liq_px)
                cost = fund[i] * abs(size) * close[i]  # long pays
                cash -= cost
                funding_total += cost
                days_long += 1
                if cur_lev >= 1.5:
                    days_2x += 1
                else:
                    days_1x += 1
        # step 2: set position for tomorrow at close[i]
        if size == 0.0 and cash <= 0.0:
            eqs[i] = 0.0
            continue
        t_dir = 1.0 if dr[i] >= 0.5 else 0.0
        t_lev = float(lv[i]) if t_dir == 1.0 else 0.0
        if np.sign(size) != t_dir:
            if size != 0.0:
                cash += size * (close[i] - entry)
                size, cur_lev = 0.0, 0.0
            if t_dir != 0.0:
                size = cash * t_lev / close[i]
                entry, cur_lev = close[i], t_lev
                switches += 1
        elif size != 0.0 and t_lev != cur_lev:
            cash += size * (close[i] - entry)  # realize, re-enter same price
            size = cash * t_lev / close[i]
            entry, cur_lev = close[i], t_lev
            resizes += 1
        eqs[i] = cash + (size * (close[i] - entry) if size != 0.0 else 0.0)

    eq = pd.Series(eqs, index=px.index)
    return eq, {"switches": switches, "resizes": resizes,
                "funding_total": funding_total, "liq": liq_events,
                "worst_wick": (worst_wick if np.isfinite(worst_wick) else None),
                "days_long": days_long, "days_1x": days_1x, "days_2x": days_2x}


def sim_spot_switch(px, state, start_cash=10000.0):
    in_market = state.shift(1).fillna(1.0)
    rets = px["close"].pct_change().fillna(0)
    eq = (1 + rets * in_market).cumprod() * start_cash
    return eq, {"switches": int((in_market.diff().abs() > 0).sum())}


def stats(eq, start_cash=10000.0):
    final = float(eq.iloc[-1])
    years = len(eq) / 365.25
    cagr = ((final / start_cash) ** (1 / years) - 1) * 100 if final > 0 else -100.0
    dd = float((eq / eq.cummax() - 1).min() * 100)
    return final, cagr, dd


def main():
    btc = load_ohlc()
    funding = load("bn_funding_btc", col="value")
    end = min(btc.index.max(), funding.index.max())
    sig = build_risk(btc)
    above = sig["above"].astype(float)
    risk = sig["risk"]

    # arms on full history (sliced per window later)
    veto_dir = (sig["above"] & (risk <= 0.7)).astype(float)
    veto_lev = veto_dir.copy()  # 1x wherever long
    tier_dir = above.copy()
    tier_lev = pd.Series(0.0, index=btc.index)
    long = sig["above"]
    tier_lev[long & (risk > 0.7)] = 0.0                      # veto -> cash
    tier_lev[long & (risk >= 0.3) & (risk <= 0.7)] = 1.0     # mid risk -> 1x
    calm_hi = long & (risk < 0.3) & sig["fund_ok"]
    tier_lev[calm_hi] = 2.0                                  # calm + gate -> 2x
    tier_lev[long & (risk < 0.3) & ~sig["fund_ok"]] = 1.0    # gate fail -> 1x
    tier_dir = (tier_lev > 0).astype(float)

    print("=== JEV-AS-RISK-GATE - risk veto / tiered leverage on MA200 direction ===")
    print(f"End: {end.date()} | funding {funding.index.min().date()}..{funding.index.max().date()} "
          f"({int(funding.notna().sum())} days, pre-2020 funding NaN -> f_fund=False, 2x gate fails safe)")
    print("risk = mean(f_fund, f_heat, f_vol); >0.7 = all three fire; <0.3 = none fire.")
    print("No lookahead: state at close d earns day d+1; trailing quantiles only; mm=0.5%, $10k/window, cash 0%.")

    windows = [("2017-01-01", "2017+ (full MA window)"),
               ("2020-01-01", "2020+ (funding era)"),
               ("2021-11-01", "2021-11 top+"),
               ("2023-01-01", "2023+ post-bear")]
    for wstart, wlabel in windows:
        w0 = pd.Timestamp(wstart, tz="UTC")
        px = btc.loc[w0:end]
        vd, vl = veto_dir.loc[w0:end], veto_lev.loc[w0:end]
        td, tl = tier_dir.loc[w0:end], tier_lev.loc[w0:end]
        ma_w = above.loc[w0:end]
        sg = sig.loc[w0:end]
        fd_w = funding.loc[w0:end]
        print(f"\n=== window {wlabel}: {px.index[0].date()} -> {px.index[-1].date()} "
              f"({len(px)}d, BTC {float(px['close'].iloc[0]):,.0f} -> {float(px['close'].iloc[-1]):,.0f}) ===")

        rows = []
        bh = (1 + px["close"].pct_change().fillna(0)).cumprod() * 10000
        rows.append(("spot buy&hold (ref)", bh, {"switches": 0, "flips": 0}))
        eq, s = sim_spot_switch(px, ma_w)
        s["flips"] = int((ma_w.diff().abs() > 0).sum())
        rows.append(("spot switch MA200 (ref)", eq, s))
        eq, s = sim_switchable(px, vd, vl, fd_w)
        s["flips"] = int((vd.diff().abs() > 0).sum())
        rows.append(("VETO 1x (MA200 + risk veto)", eq, s))
        eq, s = sim_switchable(px, td, tl, fd_w)
        s["flips"] = int((td.diff().abs() > 0).sum())
        rows.append(("TIERED 2x/1x/cash (MA200 + gate)", eq, s))

        print(f"{'arm':34} {'final $':>10} {'CAGR':>7} {'maxDD':>7} "
              f"{'flips':>5} {'funding $':>10} {'liq':>4} {'switch':>6} {'rsz':>4}")
        for name, eq, s in rows:
            if eq.iloc[-1] == 0 and s.get("liq"):
                print(f"{name:34} {'LIQUIDATED':>10} {'':>7} {str(s['liq'][0]):>7}")
                continue
            final, cagr, dd = stats(eq)
            fnd = s.get("funding_total")
            ftxt = f"{fnd:>10,.0f}" if fnd is not None else f"{'-':>10}"
            print(f"{name:34} {final:>10,.0f} {cagr:>+6.1f}% {dd:>6.1f}% "
                  f"{s.get('flips', 0):>5} {ftxt} {len(s.get('liq', [])):>4} "
                  f"{s.get('switches', 0):>6} {s.get('resizes', 0):>4}")

        # flag counts + risk histogram + positioning
        r = sg["risk"]
        print(f"flags (days): f_fund={int(sg['f_fund'].sum())} f_heat={int(sg['f_heat'].sum())} "
              f"f_vol={int(sg['f_vol'].sum())} | risk==0:{int((r == 0).sum())} "
              f"1/3:{int((r == 1/3).sum())} 2/3:{int((r == 2/3).sum())} 1:{int((r == 1).sum())} | "
              f"veto days (risk>0.7)={int((r > 0.7).sum())} "
              f"binding (veto+MA-long)={int(((r > 0.7) & sg['above']).sum())}")
        # positioned-day counts from the TIERED sim stats (rerun for clarity):
        _, ts = sim_switchable(px, td, tl, fd_w)
        print(f"positioning: TIERED 2x-days={ts['days_2x']} 1x-days={ts['days_1x']} "
              f"(of {ts['days_long']} positioned days)")

        # veto precision: forward-5d return on vetoed-long days vs non-vetoed-long days
        fwd5 = px["close"].shift(-5) / px["close"] - 1
        uni = sg["above"] & fwd5.notna()
        v = (sg["risk"] > 0.7) & uni
        nv = ~(sg["risk"] > 0.7) & uni
        if int(v.sum()) > 0 and int(nv.sum()) > 0:
            mv, mn = fwd5[v].mean() * 100, fwd5[nv].mean() * 100
            hv, hn = (fwd5[v] < 0).mean() * 100, (fwd5[nv] < 0).mean() * 100
            print(f"veto precision (MA-long days, fwd-5d): n_veto={int(v.sum())} "
                  f"mean {mv:+.2f}% | n_nonveto={int(nv.sum())} mean {mn:+.2f}% | "
                  f"diff {mv - mn:+.2f}pp | neg-rate veto {hv:.0f}% vs nonveto {hn:.0f}%")
        else:
            print(f"veto precision: n_veto={int(v.sum())} (insufficient veto days)")

    print("\nStateless: results printed above, nothing saved.")


if __name__ == "__main__":
    main()
