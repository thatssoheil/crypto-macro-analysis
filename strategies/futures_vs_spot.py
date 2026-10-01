#!/usr/bin/env python3
"""
FUTURES vs SPOT STUDY - leveraged long positions on BTC (2020-2026).

Owner question (2026-10-01): instead of spot buying and selling across regimes,
what do leveraged long-term FUTURES positions do - constant and regime-switched?

Method (house conventions, see AGENTS.md):
  - Price: Bitstamp BTC daily OHLC (the series the house backtests use).
  - Funding: bn_funding_btc.csv = daily SUM of the 8h Binance BTCUSDT rates
    (fraction/day; the exchange-published archive, complete 2020-01-01..2026-09-30).
    Funding is a HOLDING COST, so unlike fees it IS charged: longs pay the rate on
    the open notional, shorts receive it (sign flip). Fees/slippage excluded.
  - Regime switch: 200d-MA filter (the validated edge) + the composite
    (score >= +0.5) as sensitivity. Composite semantics are taken from the LIVE
    engine macro_regime_v3.py, not from the v4 replay script (which diverges on
    three high-is-good signals: stablecoin, M2, Fed balance sheet).
  - No lookahead: the position earning day t's move is decided by day t-1
    (spot arms: the exact v4 .shift(1) convention; futures arms: switch executed
    at the close where the state becomes known).
  - Futures accounting: all capital posted as isolated margin; notional = L x equity
    at entry; set-and-forget (no rebalancing, leverage drifts); mark-to-market on
    closes; LIQUIDATION when the daily LOW/HIGH breaches the maintenance price
    (mm = 0.5%, BTCUSDT low tier) - the liquidation test is exact against the
    funding-drifted equity, not the static entry formula.
  - Cash earns 0%. $10k start. Windows: full 2020-01..now, last top 2021-11..now,
    post-bear 2023-01..now. Results print to stdout (stateless - nothing saved).
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "macro_dataset"
MM = 0.005  # maintenance margin rate (BTCUSDT low notional tier ~0.4-0.5%; 0.5% conservative)


def load(name, date_col="date", col="close"):
    df = pd.read_csv(DATA / f"{name}.csv")
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    return df[col]


def slope(s, n=200):
    """+1 above n-MA, -1 below, 0 equal (engine slope_score)."""
    ma = s.rolling(n).mean()
    return np.sign(s - ma)


def bands(s, lo_v, hi_v):
    """Engine threshold signal: +1 below lo_v, -1 above hi_v, else 0."""
    out = pd.Series(0.0, index=s.index)
    out[s < lo_v] = 1.0
    out[s > hi_v] = -1.0
    return out


def hi_good(s, lo_lo, hi_lo):
    """Engine high-is-good signal: +1 above hi_lo, -1 below lo_lo, else 0."""
    out = pd.Series(0.0, index=s.index)
    out[s > hi_lo] = 1.0
    out[s < lo_lo] = -1.0
    return out


def load_ohlc():
    df = pd.read_csv(DATA / "btcusd_daily_bitstamp.csv")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()[["open", "high", "low", "close"]]


def engine_score(idx):
    """Pointwise daily replay of the LIVE engine's 14 signals (macro_regime_v3.py
    semantics). Daily lags match the engine within one row."""
    sig = {}
    u10 = load("us10y"); u3m = load("us3m")
    curve = (u10 - u3m.reindex(u10.index).ffill()).dropna()
    sig["curve"] = (pd.Series(np.where(curve > 0, 1.0, -1.0), index=curve.index), 2.0)

    stab = load("stablecoin_total_liquidity", col="total_cap_usd")
    g = stab / stab.shift(30) - 1
    sig["stablecoin"] = (hi_good(g, -0.02, 0.02), 2.0)

    sig["dxy"] = (slope(load("dxy")), 1.5)

    m2 = load("fred_us_m2", col="value")
    yoy = m2 / m2.shift(12) - 1
    sig["m2"] = (hi_good(yoy, 0.01, 0.04), 2.0)

    fbs = load("fred_fed_balance_sheet", col="value")
    chg = fbs / fbs.shift(60) - 1
    sig["fed_bs"] = (hi_good(chg, -0.01, 0.01), 1.5)

    vix = load("vix")
    sig["vix"] = (bands(vix, 20.0, 30.0), 1.5)

    sig["spx"] = (slope(load("sp500")), 1.5)

    hy = load("fred_hy_spread", col="value")
    sig["credit"] = (bands(hy, 3.5, 5.5), 1.5)

    sig["btc_ma"] = (slope(load("btcusd_daily_bitstamp", "ts")), 2.0)

    fng = load("fear_greed", col="value")
    sig["fng"] = (bands(fng, 30.0, 70.0), 1.0)

    hash_s = load("bi_hash-rate", "ts", "value")
    sig["hash"] = (slope(hash_s, 60), 0.5)

    ry = load("fred_real_yield10y", col="value")
    sig["real_yield"] = (bands(ry, 1.5, 2.5), 1.0)

    cpi = load("fred_cpi", col="value")
    cy = cpi / cpi.shift(12) - 1
    sig["cpi"] = (bands(cy, 0.03, 0.05), 0.5)

    sig["gold"] = (slope(load("gold")), 0.5)

    WTS = {k: v for k, (_, v) in sig.items()}
    avail = {}
    for k, (s, w) in sig.items():
        avail[k] = s.reindex(idx).ffill()
    sig_df = pd.DataFrame(avail)
    wsum = (sig_df.notna() * pd.Series(WTS)).sum(axis=1)
    return (sig_df.fillna(0) * pd.Series(WTS)).sum(axis=1) / wsum * 3


def sim_spot_switch(px, state, start_cash=10000.0):
    """Spot: long when state=1 else cash 0%; the exact v4 convention (shift(1))."""
    in_market = state.shift(1).fillna(1.0)
    rets = px["close"].pct_change().fillna(0)
    eq = (1 + rets * in_market).cumprod() * start_cash
    return eq, {"switches": int((in_market.diff().abs() > 0).sum())}


def sim_futures(px, state, lev, funding, short_out=False, start_cash=10000.0):
    """Futures loop. state: raw (unshifted) daily state series (1/0, or fraction).
    short_out=True -> desired direction = +1 in state, -1 out of state (always in).
    Position earning day i's move is set at close[i-1]; switches at the close where
    the state becomes known. Returns (equity series, stats dict)."""
    close = px["close"].to_numpy(float)
    low = px["low"].to_numpy(float)
    high = px["high"].to_numpy(float)
    st = state.to_numpy(float)
    fund = funding.reindex(px.index).fillna(0.0).to_numpy(float)
    n = len(close)

    cash = start_cash          # realized equity basis (tracks equity while size=0)
    size = 0.0                 # signed BTC
    entry = 0.0
    eqs = np.zeros(n)
    funding_total = 0.0
    switches = 0
    liq_events = []
    worst_wick = np.inf        # min over positioned days of low[i]/liq_px (long) etc.
    days_long = days_short = 0

    def desired(i):
        if short_out:
            return 1.0 if st[i] >= 0.5 else -1.0
        return 1.0 if st[i] >= 0.5 else 0.0

    for i in range(n):
        # ---- step 1: mark day i's move + funding on the position held from close[i-1]
        if size != 0.0 and i > 0:
            prev_close = close[i - 1]
            equity_prev = cash + size * (prev_close - entry)
            dead = False
            if size > 0:
                liq_px = (size * prev_close - equity_prev) / (size * (1 - MM))
                wick = low[i]
                if wick <= liq_px:
                    liq_events.append(str(px.index[i].date()) + " long")
                    dead = True
                else:
                    worst_wick = min(worst_wick, wick / liq_px)
                days_long += 1
            else:
                liq_px = (equity_prev - size * prev_close) / (-size * (1 + MM))
                wick = high[i]
                if wick >= liq_px:
                    liq_events.append(str(px.index[i].date()) + " short")
                    dead = True
                else:
                    worst_wick = min(worst_wick, liq_px / wick)
                days_short += 1
            if dead:
                cash = 0.0; size = 0.0
            else:
                # funding accrued over day i on the open notional, then mark to close
                cost = np.sign(size) * fund[i] * abs(size) * close[i]
                cash -= cost
                funding_total += cost
        # ---- step 2: set the position for tomorrow at close[i] (state[i] now known)
        if size == 0.0 and cash <= 0.0:
            eqs[i] = 0.0
            continue
        target = desired(i)
        if np.sign(size) != target:
            if size != 0.0:                       # close at close price
                cash += size * (close[i] - entry)
                size = 0.0
            if target != 0.0:
                notional = cash * lev
                size = target * notional / close[i]
                entry = close[i]
                switches += 1
        eqs[i] = cash + (size * (close[i] - entry) if size != 0.0 else 0.0)

    eq = pd.Series(eqs, index=px.index)
    return eq, {
        "switches": switches, "funding_total": funding_total, "liq": liq_events,
        "worst_wick": (worst_wick if np.isfinite(worst_wick) else None),
        "days_long": days_long, "days_short": days_short,
    }


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
    print(f"=== FUTURES vs SPOT - leveraged long-term BTC study ===")
    print(f"Window end: {end.date()} | funding days: {int(funding.loc[:end].notna().sum())} "
          f"(first {funding.index.min().date()})")

    close = btc["close"]
    ma_state = (close >= close.rolling(200).mean()).astype(float)
    score = engine_score(btc.index)
    comp_state = (score >= 0.5).astype(float)

    # --- validations (house facts) ---
    flips = ma_state.diff().fillna(0)
    last_exit = ma_state.index[(flips == -1)][-1].date() if (flips == -1).any() else None
    last_entry = ma_state.index[(flips == 1)][-1].date() if (flips == 1).any() else None
    print(f"MA200 state: last exit {last_exit}, last re-entry {last_entry} "
          f"(AGENTS.md says 2025-11-03 / 2026-08-19)")
    d923 = pd.Timestamp("2026-09-23", tz="UTC")
    print(f"engine-consistent score at 2026-09-23: {float(score.loc[d923]):+.1f} (house read: ~+1.7)")

    # --- funding cost table ---
    print("\n--- funding: annual drag if always long (real Binance rates) ---")
    f = funding.copy()
    print(f"{'year':5} {'days':>5} {'sum of daily rates':>18} {'=annualized drag':>16}")
    for yr, grp in f.groupby(f.index.year):
        print(f"{yr:5} {len(grp):>5} {grp.sum()*100:>17.1f}% {grp.sum()*100:>15.1f}%")
    print(f"cumulative funding if always long over the window: {f.sum()*100:,.1f}% "
          f"(~{f.sum()*100/ (len(f)/365.25):,.1f}%/yr)")
    in_mkt = ma_state.shift(1).fillna(1.0)
    fc = f.index.intersection(in_mkt.index)
    m = in_mkt.reindex(fc) == 1
    print(f"avg daily rate | in-market days: {f.reindex(fc)[m].mean()*100:+.4f}% "
          f"| out-of-market days: {f.reindex(fc)[~m].mean()*100:+.4f}%")

    # --- windows ---
    windows = [("2020-01-01", "full (2020-01..now)"),
               ("2021-11-01", "last top (2021-11..now)"),
               ("2023-01-01", "post-bear (2023-01..now)")]
    for wstart, wlabel in windows:
        w0 = pd.Timestamp(wstart, tz="UTC")
        px = btc.loc[w0:end]
        ma_w = ma_state.reindex(px.index)
        comp_w = comp_state.reindex(px.index)
        fd_w = funding.loc[w0:end]
        print(f"\n=== window {wlabel}: {px.index[0].date()} -> {px.index[-1].date()} "
              f"({len(px)} days, BTC {float(px['close'].iloc[0]):,.0f} -> {float(px['close'].iloc[-1]):,.0f}) ===")
        # spot baselines
        bh = (1 + px["close"].pct_change().fillna(0)).cumprod() * 10000
        rows = [("spot buy&hold", bh, {})]
        eq, s = sim_spot_switch(px, ma_w); rows.append(("spot switch MA200", eq, s))
        eq, s = sim_spot_switch(px, comp_w); rows.append(("spot switch composite", eq, s))
        # futures arms
        for lev in (1.5, 2.0, 3.0):
            eq, s = sim_futures(px, pd.Series(1.0, index=px.index), lev, fd_w)
            rows.append((f"futures {lev}x constant", eq, s))
        for lev in (1.5, 2.0, 3.0):
            eq, s = sim_futures(px, ma_w, lev, fd_w)
            rows.append((f"futures {lev}x switch MA200", eq, s))
        eq, s = sim_futures(px, comp_w, 2.0, fd_w)
        rows.append(("futures 2x switch composite", eq, s))
        eq, s = sim_futures(px, ma_w, 2.0, fd_w, short_out=True)
        rows.append(("futures 2x always-in (long/short)", eq, s))

        print(f"{'arm':38} {'final $':>12} {'CAGR':>7} {'maxDD':>7} {'liq':>4} {'funding $':>10} {'switches':>8}")
        for name, eq, s in rows:
            if eq.iloc[-1] == 0 and s.get("liq"):
                print(f"{name:38} {'LIQUIDATED':>12} {'':>7} {str(s['liq'][0]):>7}")
                continue
            final, cagr, dd = stats(eq)
            fnd = s.get("funding_total", 0.0)
            wick = s.get("worst_wick")
            wtxt = f" wick-close {wick:.2f}x" if wick is not None else ""
            print(f"{name:38} {final:>12,.0f} {cagr:>+6.1f}% {dd:>6.1f}% "
                  f"{len(s.get('liq', [])):>4} {fnd:>10,.0f} {s.get('switches', 0):>8}{wtxt}")

    print("\n--- liquidation distance ladder (static, mm=0.5%) ---")
    for lev in (1.5, 2.0, 3.0, 5.0):
        print(f"  {lev:>3}x -> liq after a {(1 - (1 - 1/lev)/(1 - MM))*100:>5.1f}% adverse move")

    print("\nStateless: results printed above, nothing saved.")


if __name__ == "__main__":
    main()
