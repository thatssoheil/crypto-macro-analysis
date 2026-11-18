#!/usr/bin/env python3
"""
CROSS-ASSET SNAPSHOT - one page of worldwide trend facts, all from the committed dataset.

Built for the council session (owner request 2026-11-18): "full image of the worldwide
trend right now, risk-off (gold) versus risk-on (stocks, crypto), and how markets may
behave in the coming months".

It answers, in numbers and without a narrative:
  1. MOMENTUM AND TREND per asset: 1w/1m/3m/6m/12m returns, distance to the 50d and
     200d, 200d slope, drawdown from the 52-week high, and the MA stack (20/50/200).
  2. RISK-ON vs RISK-OFF ratios: SPX/gold, copper/gold, BTC/gold, ETH/BTC, and the
     count of assets trading above their 200d (breadth).
  3. THE PLUMBING: curve, real yield, breakevens, credit spreads, VIX, dollar,
     net liquidity (Fed balance sheet - TGA - RRP), M2 YoY, stablecoin supply.
  4. CRYPTO INTERNALS: total cap, BTC dominance, per-asset trend state.

Every line states its own as-of date, because the sources do not close together:
Yahoo macro series lag by a few days, FRED by weeks, crypto is same-day.

Stateless: prints to stdout, saves nothing.
"""
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"

# name -> (chart, date column, column)
ASSETS = [
    ("SPX", "sp500", "date", "close"),
    ("NASDAQ", "nasdaq", "date", "close"),
    ("RUSSELL 2000", "russell2000", "date", "close"),
    ("VIX", "vix", "date", "close"),
    ("DXY", "dxy", "date", "close"),
    ("US 10Y", "us10y", "date", "close"),
    ("US 30Y", "us30y", "date", "close"),
    ("GOLD", "gold", "date", "close"),
    ("SILVER", "silver", "date", "close"),
    ("WTI", "wti", "date", "close"),
    ("COPPER", "copper", "date", "close"),
    ("BTC", "btcusd_daily_bitstamp", "ts", "close"),
    ("ETH", "ethusd_daily_bitstamp", "ts", "close"),
    ("SOL", "solusd_daily_yahoo", "ts", "close"),
    ("ZEC", "zecusd_daily_bitfinex", "ts", "close"),
]


def load(chart, dcol="date", col="close"):
    p = DATA / f"{chart}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df[dcol] = pd.to_datetime(df[dcol], utc=True)
    df = df.set_index(dcol).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if col not in df.columns:
        return None
    return pd.to_numeric(df[col], errors="coerce").dropna()


def ret(s, days):
    base = s.loc[:s.index[-1] - pd.Timedelta(days=days)]
    if base.empty:
        return np.nan
    return float(s.iloc[-1] / base.iloc[-1] - 1) * 100


def pct_from(s, ma):
    if ma != ma:
        return np.nan
    return float(s.iloc[-1] / ma - 1) * 100


def main():
    print("=" * 118)
    print("CROSS-ASSET SNAPSHOT   generated " + pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC"))
    print("=" * 118)

    print("\n[1] MOMENTUM AND TREND (percent; distance to MA in percent; DD from the 52w high)")
    print(f"{'asset':<12}{'as of':<12}{'last':>11}{'1w':>8}{'1m':>8}{'3m':>9}{'6m':>9}{'12m':>9}"
          f"{'vs50d':>8}{'vs200d':>9}{'200d sl':>9}{'DD52w':>8}{'stack':>12}")
    print("-" * 118)
    above200 = 0
    counted = 0
    for name, chart, dcol, col in ASSETS:
        s = load(chart, dcol, col)
        if s is None or len(s) < 220:
            continue
        ma20, ma50, ma200 = (s.rolling(n).mean() for n in (20, 50, 200))
        stack = ("20>50>200" if ma20.iloc[-1] > ma50.iloc[-1] > ma200.iloc[-1]
                 else "20<50<200" if ma20.iloc[-1] < ma50.iloc[-1] < ma200.iloc[-1]
                 else "mixed")
        hi52 = s.loc[s.index[-1] - pd.Timedelta(days=365):].max()
        if name not in ("VIX",):
            counted += 1
            above200 += int(s.iloc[-1] > ma200.iloc[-1])
        print(f"{name:<12}{s.index[-1]:%Y-%m-%d}  {s.iloc[-1]:>10,.2f}{ret(s,7):>+8.1f}{ret(s,30):>+8.1f}"
              f"{ret(s,91):>+9.1f}{ret(s,182):>+9.1f}{ret(s,365):>+9.1f}"
              f"{pct_from(s, ma50.iloc[-1]):>+8.1f}{pct_from(s, ma200.iloc[-1]):>+9.1f}"
              f"{(ma200.iloc[-1]/ma200.iloc[-31]-1)*100:>+9.2f}{(s.iloc[-1]/hi52-1)*100:>+8.1f}  {stack:>12}")
    print(f"\n  breadth: {above200} of {counted} trend assets above their 200d MA "
          f"({above200/max(counted,1)*100:.0f}%)")

    print("\n[2] RISK-ON versus RISK-OFF RATIOS")
    def ratio(a, b):
        sa, sb = load(*a), load(*b)
        if sa is None or sb is None:
            return None
        r = (sa / sb.reindex(sa.index, method="ffill")).dropna()
        return r
    pairs = [
        ("SPX / GOLD", ("sp500", "date", "close"), ("gold", "date", "close")),
        ("COPPER / GOLD", ("copper", "date", "close"), ("gold", "date", "close")),
        ("BTC / GOLD", ("btcusd_daily_bitstamp", "ts", "close"), ("gold", "date", "close")),
        ("ETH / BTC", ("ethusd_daily_bitstamp", "ts", "close"), ("btcusd_daily_bitstamp", "ts", "close")),
        ("SOL / BTC", ("solusd_daily_yahoo", "ts", "close"), ("btcusd_daily_bitstamp", "ts", "close")),
        ("ZEC / BTC", ("zecusd_daily_bitfinex", "ts", "close"), ("btcusd_daily_bitstamp", "ts", "close")),
    ]
    print(f"{'ratio':<16}{'as of':<12}{'last':>12}{'1m':>9}{'3m':>9}{'6m':>9}{'12m':>9}{'vs200d':>9}{'200d sl':>9}")
    print("-" * 96)
    for label, a, b in pairs:
        r = ratio(a, b)
        if r is None or len(r) < 220:
            continue
        ma = r.rolling(200).mean()
        print(f"{label:<16}{r.index[-1]:%Y-%m-%d}  {r.iloc[-1]:>11.6f}{ret(r,30):>+9.1f}{ret(r,91):>+9.1f}"
              f"{ret(r,182):>+9.1f}{ret(r,365):>+9.1f}{pct_from(r, ma.iloc[-1]):>+9.1f}"
              f"{(ma.iloc[-1]/ma.iloc[-31]-1)*100:>+9.2f}")

    print("\n[3] PLUMBING (levels and recent direction)")
    rows = []

    def add(label, value, note=""):
        rows.append((label, value, note))

    u10, u3m, u2y = load("us10y"), load("us3m"), load("us2y")
    if u10 is not None and u3m is not None:
        c = (u10 - u3m.reindex(u10.index).ffill()).dropna()
        add("curve 10y-3m", f"{c.iloc[-1]:+.2f}%", f"90d ago {c.loc[:c.index[-1]-pd.Timedelta(days=90)].iloc[-1]:+.2f}%")
    if u10 is not None and u2y is not None:
        c = (u10 - u2y.reindex(u10.index).ffill()).dropna()
        add("curve 10y-2y", f"{c.iloc[-1]:+.2f}%", f"90d ago {c.loc[:c.index[-1]-pd.Timedelta(days=90)].iloc[-1]:+.2f}%")
    ry = load("fred_real_yield10y", col="value")
    if ry is not None:
        add("10y real yield", f"{ry.iloc[-1]:.2f}%", f"as of {ry.index[-1]:%Y-%m-%d}, 90d ago {ry.loc[:ry.index[-1]-pd.Timedelta(days=90)].iloc[-1]:.2f}%")
    be = load("fred_breakeven10y", col="value")
    if be is not None:
        add("10y breakeven", f"{be.iloc[-1]:.2f}%", f"as of {be.index[-1]:%Y-%m-%d}")
    hy = load("fred_hy_spread", col="value")
    if hy is not None:
        add("HY credit spread", f"{hy.iloc[-1]:.2f}%", f"as of {hy.index[-1]:%Y-%m-%d}, 90d ago {hy.loc[:hy.index[-1]-pd.Timedelta(days=90)].iloc[-1]:.2f}%")
    ig = load("fred_ig_spread", col="value")
    if ig is not None:
        add("IG credit spread", f"{ig.iloc[-1]:.2f}%", f"as of {ig.index[-1]:%Y-%m-%d}")
    cpi = load("fred_cpi", col="value")
    if cpi is not None:
        yoy = (cpi.iloc[-1] / cpi.loc[:cpi.index[-1] - pd.Timedelta(days=365)].iloc[-1] - 1) * 100
        add("CPI YoY", f"{yoy:+.1f}%", f"as of {cpi.index[-1]:%Y-%m-%d}")
    m2 = load("fred_us_m2", col="value")
    if m2 is not None:
        yoy = (m2.iloc[-1] / m2.loc[:m2.index[-1] - pd.Timedelta(days=365)].iloc[-1] - 1) * 100
        add("M2 YoY", f"{yoy:+.1f}%", f"as of {m2.index[-1]:%Y-%m-%d}")
    fbs = load("fred_fed_balance_sheet", col="value")
    tga = load("fred_tga", col="value")
    rrp = load("fred_rrp", col="value")
    if fbs is not None and tga is not None and rrp is not None:
        # Net liquidity = Fed balance sheet - Treasury General Account - reverse repo.
        # TGA is served in USD millions by FiscalData/FRED WTREGEN (billions) - normalise to billions.
        f = fbs.copy()
        t = tga.copy()
        if t.iloc[-1] > 1e6:            # FiscalData daily file is in millions
            t = t / 1000.0
        r = rrp.copy()
        idx = f.index.union(t.index).union(r.index)
        nl = (f.reindex(idx).ffill() - t.reindex(idx).ffill() - r.reindex(idx).ffill() / 1000.0).dropna()
        add("net liquidity (BS-TGA-RRP)", f"${nl.iloc[-1]/1000:,.0f}B",
            f"90d chg ${(nl.iloc[-1]-nl.loc[:nl.index[-1]-pd.Timedelta(days=90)].iloc[-1])/1000:+,.0f}B")
    add("VIX level", f"{load('vix').iloc[-1]:.1f}", "below 20 = calm, above 30 = stress")
    stab = load("stablecoin_total_liquidity", col="total_cap_usd")
    if stab is not None:
        add("stablecoin supply", f"${stab.iloc[-1]/1e9:,.1f}B", f"30d {(stab.iloc[-1]/stab.loc[:stab.index[-1]-pd.Timedelta(days=30)].iloc[-1]-1)*100:+.1f}%")
    tot = load("cmc_total_mcap", col="total_mcap_usd")
    if tot is not None:
        add("total crypto cap", f"${tot.iloc[-1]/1e12:,.2f}T", f"30d {(tot.iloc[-1]/tot.loc[:tot.index[-1]-pd.Timedelta(days=30)].iloc[-1]-1)*100:+.1f}%")
    btcd = load("cmc_total_mcap", col="btc_dominance")
    ethd = load("cmc_total_mcap", col="eth_dominance")
    if btcd is not None:
        add("BTC / ETH dominance", f"{btcd.iloc[-1]:.1f}% / {ethd.iloc[-1]:.1f}%",
            f"BTC 30d ago {btcd.loc[:btcd.index[-1]-pd.Timedelta(days=30)].iloc[-1]:.1f}%")
    fng = load("fear_greed", col="value")
    if fng is not None:
        add("Fear & Greed", f"{float(fng.iloc[-1]):.0f}", "crypto sentiment, contrarian at extremes")
    for label, value, note in rows:
        print(f"  {label:<28} {value:>16}   {note}")

    print("\n[4] HOW TO READ THIS")
    print("  Trend is not a forecast: every line above is a state, and states persist more")
    print("  often than they reverse. The council's job is to say which states are about to")
    print("  break and what would prove it, not to extrapolate the last three months.")


if __name__ == "__main__":
    main()
