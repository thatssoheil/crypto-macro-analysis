#!/usr/bin/env python3
"""
SOL MACRO PICTURE - the raw numbers behind the Solana regime read.

Answers the standing request "give me the data" for SOL: daily and weekly
history, volume, the chain-economics charts, the derivatives positioning and the
shared macro backdrop, all in one stdout report. The verdict itself lives in
strategies/sol_macro_regime.py; this file is the tape.

Conventions:
  - Price: solusd_daily_yahoo (longest keyless series, 2020-04-10 ->), cross-checked
    against the OKX venue print. Weekly bars are a deterministic resample of the
    daily closes that END on Sunday (Mon-Sun week), never a separate source.
  - Every change window is calendar-anchored (days), never a row offset - the Solana
    stablecoin chart is sparse before 2023.
  - The newest daily bar is labelled PROVISIONAL: it is still forming at Yahoo and
    becomes final at the next UTC close.
  - Weekly moving averages are named by their DAY equivalent: 28w = 196d, 7w = 49d.

Stateless: prints to stdout, saves nothing.
"""
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"


def load(name, date_col="date", col="close"):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[col] if col in df.columns else df


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def chg(s, days):
    """Calendar-anchored change, in percent."""
    if s is None or len(s) < 2:
        return float("nan")
    cut = s.index[-1] - pd.Timedelta(days=days)
    base = s.loc[:cut]
    if base.empty:
        return float("nan")
    return float((s.iloc[-1] / base.iloc[-1] - 1) * 100)


def weekly(daily):
    w = daily.resample("W-SUN").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    return w.dropna(subset=["close"])


def pct_rank_last(s, years=2):
    cut = s.index[-1] - pd.Timedelta(days=365 * years)
    hist = s.loc[cut:]
    if len(hist) < 30:
        return float("nan")
    return float((hist <= s.iloc[-1]).mean() * 100)


def money(v):
    """Compact USD: B / M / K, never a bare 0.0M."""
    if v >= 1e9:
        return f"${v/1e9:,.2f}B"
    if v >= 1e6:
        return f"${v/1e6:,.1f}M"
    if v >= 1e3:
        return f"${v/1e3:,.0f}K"
    return f"${v:,.0f}"


def bar_line(label, value, note=""):
    print(f"  {label:<34} {value:>28}   {note}")


def main():
    px = load("solusd_daily_yahoo", "ts")
    if px is None:
        raise SystemExit("solusd_daily_yahoo.csv missing - run build_macro_dataset.py --solana-only")
    px = px[~px.index.duplicated(keep="last")].sort_index().dropna()
    now = datetime.now(timezone.utc)
    today = px.index[-1]

    btc = load("btcusd_daily_bitstamp", "ts")
    eth = load("ethusd_daily_bitstamp", "ts")
    okx = load("solusd_daily_okx", "ts")

    ma50, ma200 = px.rolling(50).mean(), px.rolling(200).mean()
    ath = px.max()
    ath_date = px.idxmax()
    dd = (px.iloc[-1] / ath - 1) * 100
    ret = np.log(px).diff()
    vol30 = ret.rolling(30).std() * np.sqrt(365) * 100

    print("=" * 78)
    print(f"SOL MACRO PICTURE   {today:%Y-%m-%d} UTC   (daily bar {'PROVISIONAL' if today.date() == now.date() else 'final'})")
    print("=" * 78)
    print(f"history        {px.index[0]:%Y-%m-%d} -> {px.index[-1]:%Y-%m-%d}   "
          f"{len(px)} daily closes, {len(weekly(px))} weekly closes")
    if okx is not None:
        print(f"cross-check    OKX {okx.index[0]:%Y-%m-%d} -> {okx.index[-1]:%Y-%m-%d}, "
              f"last close ${okx.iloc[-1]:,.2f} vs Yahoo ${px.iloc[-1]:,.2f} "
              f"({(okx.iloc[-1]/px.iloc[-1]-1)*100:+.2f}% basis)")

    # ------------------------------------------------------------------ daily tape
    print("\n[1] DAILY TAPE")
    bar_line("close", f"${px.iloc[-1]:,.2f}")
    for d, lbl in ((1, "1d"), (7, "7d"), (30, "30d"), (90, "90d"), (365, "1y")):
        bar_line(f"change {lbl}", f"{chg(px, d):+.1f}%")
    hi = load("solusd_daily_yahoo", "ts", col="high")
    hi_ath = float(hi.max()) if hi is not None else float("nan")
    bar_line("ATH (close basis)", f"${ath:,.2f}  ({ath_date:%Y-%m-%d})")
    bar_line("ATH (intraday high)", f"${hi_ath:,.2f}  ({hi.idxmax():%Y-%m-%d})" if hi is not None else "n/a")
    bar_line("drawdown from ATH", f"{dd:+.1f}%")
    bar_line("50d MA", f"${ma50.iloc[-1]:,.2f}  ({(px.iloc[-1]/ma50.iloc[-1]-1)*100:+.1f}%)")
    bar_line("200d MA", f"${ma200.iloc[-1]:,.2f}  ({(px.iloc[-1]/ma200.iloc[-1]-1)*100:+.1f}%)")
    bar_line("200d MA slope 30d", f"{(ma200.iloc[-1]/ma200.iloc[-31]-1)*100:+.2f}%")
    bar_line("RSI(14) daily", f"{rsi(px).iloc[-1]:.1f}")
    bar_line("realized vol 30d (ann.)", f"{vol30.iloc[-1]:.0f}%")
    bar_line("90d high / low", f"${px.loc[px.index[-1]-pd.Timedelta(days=90):].max():,.2f} / "
                              f"${px.loc[px.index[-1]-pd.Timedelta(days=90):].min():,.2f}")

    vol = load("solusd_daily_yahoo", "ts", col="volume")
    if vol is not None:
        v30, v90 = vol.tail(30).mean(), vol.tail(90).mean()
        bar_line("volume 30d avg (USD)", f"${v30/1e9:,.2f}B", f"vs 90d ${v90/1e9:,.2f}B ({v30/v90:.2f}x)")

    # ----------------------------------------------------------------- weekly tape
    print("\n[2] WEEKLY TAPE (resampled from the same daily closes, weeks end Sunday)")
    w = weekly(px)
    wma7, wma28 = w["close"].rolling(7).mean(), w["close"].rolling(28).mean()
    partial = "  [IN PROGRESS week]" if (now - w.index[-1]).days < 7 and w.index[-1].date() >= (now - pd.Timedelta(days=7)).date() else ""
    bar_line("last weekly close", f"${w['close'].iloc[-1]:,.2f}  (week ending {w.index[-1]:%Y-%m-%d}){partial}")
    bar_line("weekly change", f"{chg(w['close'], 7):+.1f}%")
    bar_line("7w MA (49d)", f"${wma7.iloc[-1]:,.2f}  ({(w['close'].iloc[-1]/wma7.iloc[-1]-1)*100:+.1f}%)")
    bar_line("28w MA (196d)", f"${wma28.iloc[-1]:,.2f}  ({(w['close'].iloc[-1]/wma28.iloc[-1]-1)*100:+.1f}%)")
    bar_line("RSI(14) weekly", f"{rsi(w['close']).iloc[-1]:.1f}")
    bar_line("weekly closes in a row up/down",
             f"{int((w['close'].diff() > 0).iloc[::-1].cumprod().sum())} up / "
             f"{int((w['close'].diff() < 0).iloc[::-1].cumprod().sum())} down")
    print("\n  last 12 weekly closes:")
    tail = w.tail(12)
    for d, r in tail.iterrows():
        arrow = "up  " if r["close"] > r["open"] else "down"
        print(f"    {d:%Y-%m-%d}  open ${r['open']:>8,.2f}  close ${r['close']:>8,.2f}  "
              f"high ${r['high']:>8,.2f}  low ${r['low']:>8,.2f}  {arrow} "
              f"{((r['close']/w['close'].shift(1).loc[d])-1)*100:+.1f}%")

    # ---------------------------------------------------------------- relative
    print("\n[3] RELATIVE STRENGTH, SOL.D AND MARKET-SHARE CONTEXT")
    for other, name, series in (("BTC", "SOL/BTC", btc), ("ETH", "SOL/ETH", eth)):
        if series is None:
            continue
        alt = series.reindex(px.index, method="ffill")
        ratio = (px / alt).dropna()
        ma = ratio.rolling(200).mean()
        peak = ratio.max()
        bar_line(f"{name} (from USD closes)", f"{ratio.iloc[-1]:.6f}",
                 f"200d MA {ma.iloc[-1]:.6f} ({(ratio.iloc[-1]/ma.iloc[-1]-1)*100:+.1f}%), "
                 f"90d {chg(ratio, 90):+.1f}%, from peak {(ratio.iloc[-1]/peak-1)*100:+.1f}%")
    venue = load("solbtc_daily_okx", "ts")
    if venue is not None and btc is not None:
        # An OKX daily candle is stamped with its OPEN (16:00 UTC), so its close lands on the
        # next UTC date. Bucket it that way, then compare with the USD-implied ratio on the
        # same dates. A single day's basis is mostly bar-boundary noise, so report the median
        # over the last 30 complete days instead of one flattering or alarming print.
        vt = pd.Series(venue.values, index=venue.index.normalize() + pd.Timedelta(days=1))
        btc_d = btc.reindex(px.index, method="ffill")
        implied = (px / btc_d).dropna()
        j = pd.concat({"venue": vt, "implied": implied}, axis=1).dropna()
        j = j.iloc[:-1] if len(j) > 1 else j                      # drop the still-forming day
        basis = ((j["venue"] / j["implied"] - 1) * 100).tail(30)
        bar_line("SOL/BTC venue vs USD-implied", f"median basis {basis.median():+.2f}%",
                 f"{len(basis)} complete days, range {basis.min():+.2f}% to {basis.max():+.2f}%")

    dom = load("sol_dominance", col="pct")
    if dom is not None:
        dom = dom.dropna()
        dm200 = float(dom.rolling(200).mean().iloc[-1])
        bar_line("SOL.D (Solana dominance)", f"{dom.iloc[-1]:.2f}%",
                 f"200d MA {dm200:.2f}%, 30d {chg(dom, 30):+.1f}%, 90d {chg(dom, 90):+.1f}%")
        bar_line("  SOL.D all-time peak", f"{dom.max():.2f}%  ({dom.idxmax():%Y-%m-%d})",
                 f"now {(dom.iloc[-1]/dom.max()-1)*100:+.1f}% from that peak")
        bar_line("  SOL.D 2y percentile", f"{pct_rank_last(dom):.0f}", "share of sessions at or below today")
    mc = load("sol_mcap_cmc", col="mcap_usd")
    tot = load("cmc_total_mcap", col="total_mcap_usd")
    if mc is not None and tot is not None:
        bar_line("SOL market cap", f"${mc.iloc[-1]/1e9:,.1f}B", f"30d {chg(mc, 30):+.1f}%")
        bar_line("total crypto market cap", f"${tot.iloc[-1]/1e12:,.2f}T", f"30d {chg(tot, 30):+.1f}%")
    btcd = load("cmc_total_mcap", col="btc_dominance")
    if btcd is not None:
        bar_line("BTC / ETH dominance", f"{btcd.iloc[-1]:.1f}% / "
                                        f"{load('cmc_total_mcap', col='eth_dominance').iloc[-1]:.1f}%",
                 "the shares SOL is competing against")

    # ------------------------------------------------------- chain economics
    print("\n[4] SOLANA CHAIN ECONOMICS (DefiLlama, keyless)")
    charts = [
        ("sol_tvl_defillama", "tvl_usd", "chain TVL"),
        ("sol_stablecoins_defillama", "usd", "stablecoin supply"),
        ("sol_fees_defillama", "fees_usd", "chain fees"),
        ("sol_fees_defillama", "revenue_usd", "chain revenue"),
    ]
    for name, col, label in charts:
        s = load(name, col=col)
        if s is None:
            continue
        s = s.dropna()
        d7 = s.tail(7).mean()
        bar_line(f"{label} (latest)", money(s.iloc[-1]), f"7d avg {money(d7)}")
        bar_line(f"  {label} 30d / 90d chg", f"{chg(s, 30):+.1f}% / {chg(s, 90):+.1f}%",
                 f"2y percentile {pct_rank_last(s):.0f}")
    dex = load("sol_dex_volume_defillama", col="usd")
    if dex is not None:
        d = dex.dropna()
        bar_line("DEX volume (latest)", money(d.iloc[-1]),
                 f"7d avg {money(d.tail(7).mean())} vs 90d median {money(d.tail(90).median())}")
        bar_line("  DEX volume 30d / 90d chg", f"{chg(d, 30):+.1f}% / {chg(d, 90):+.1f}%",
                 f"2y percentile {pct_rank_last(d):.0f}")
        tvl = load("sol_tvl_defillama", col="tvl_usd")
        if tvl is not None:
            t = tvl.dropna()
            bar_line("DEX volume / TVL (7d)", f"{(d.tail(7).mean()/t.iloc[-1]):.2f}x",
                     "venue turnover; >1x is a hot retail tape")

    # ------------------------------------------------------------ derivatives
    print("\n[5] DERIVATIVES POSITIONING (Binance USD-M archive + Deribit, keyless)")
    oi = load("bn_oi_sol", col="value")
    if oi is not None:
        oi = oi.dropna()
        oi_usd = oi * px.reindex(oi.index, method="ffill")
        bar_line("open interest", f"{oi.iloc[-1]/1e6:,.2f}M SOL",
                 f"${oi_usd.iloc[-1]/1e9:,.2f}B at close")
        bar_line("  OI 30d change", f"{chg(oi_usd, 30):+.1f}% (USD)", f"2y percentile {pct_rank_last(oi_usd):.0f}")
    fund = load("bn_funding_sol", col="value")
    if fund is not None:
        f = fund.dropna()
        bar_line("funding (daily sum, last)", f"{f.iloc[-1]*100:+.4f}%",
                 f"7d {f.tail(7).sum()*100:+.4f}%  30d {f.tail(30).sum()*100:+.4f}%")
        bar_line("  funding 90d mean", f"{f.tail(90).mean()*100:+.4f}%/day",
                 f"positive = longs paying (crowded long)")
    lsr = load("bn_lsr_sol", col="value")
    if lsr is not None:
        l = lsr.dropna()
        bar_line("top-trader long/short", f"{l.iloc[-1]:.3f}",
                 f"30d ago {l.loc[:l.index[-1]-pd.Timedelta(days=30)].iloc[-1]:.3f}")
    taker = load("bn_taker_sol", col="value")
    if taker is not None:
        t = taker.dropna()
        bar_line("taker buy/sell (last)", f"{t.iloc[-1]:.3f}", f"30d mean {t.tail(30).mean():.3f}")
    dvol = load("dvol_sol", col="value")
    if dvol is not None:
        dv = dvol.dropna()
        bar_line("DVOL (implied vol)", f"{dv.iloc[-1]:.1f}",
                 f"30d ago {dv.loc[:dv.index[-1]-pd.Timedelta(days=30)].iloc[-1]:.1f}, "
                 f"1y percentile {pct_rank_last(dv, 1):.0f}")

    # ------------------------------------------------------------ macro backdrop
    print("\n[6] SHARED MACRO BACKDROP (the same inputs the BTC/ETH engines read)")
    dxy = load("dxy")
    if dxy is not None:
        bar_line("DXY", f"{dxy.iloc[-1]:.2f}",
                 f"200d MA {dxy.rolling(200).mean().iloc[-1]:.2f} "
                 f"({'firm - headwind' if dxy.iloc[-1] > dxy.rolling(200).mean().iloc[-1] else 'soft - tailwind'})")
    u10, u3m = load("us10y"), load("us3m")
    if u10 is not None and u3m is not None:
        curve = (u10 - u3m.reindex(u10.index).ffill()).dropna()
        bar_line("10y-3m curve", f"{curve.iloc[-1]:+.2f}%", f"90d ago {curve.loc[:curve.index[-1]-pd.Timedelta(days=90)].iloc[-1]:+.2f}%")
    m2 = load("fred_us_m2", col="value")
    if m2 is not None:
        base = m2.loc[:m2.index[-1] - pd.Timedelta(days=365)]
        bar_line("US M2 YoY", f"{(m2.iloc[-1]/base.iloc[-1]-1)*100:+.1f}%", f"level {m2.iloc[-1]:,.0f} (FRED M2SL)")
    stab = load("stablecoin_total_liquidity", col="total_cap_usd")
    if stab is not None:
        bar_line("total stablecoin cap", f"${stab.iloc[-1]/1e9:,.1f}B", f"30d {chg(stab, 30):+.1f}%")
    vix = load("vix")
    if vix is not None:
        bar_line("VIX", f"{vix.iloc[-1]:.1f}")
    spx = load("sp500")
    if spx is not None:
        bar_line("SPX", f"{spx.iloc[-1]:,.0f}",
                 f"200d MA {spx.rolling(200).mean().iloc[-1]:,.0f}")
    hy = load("fred_hy_spread", col="value")
    if hy is not None:
        bar_line("HY credit spread", f"{hy.iloc[-1]:.2f}%")
    fng = load("fear_greed", col="value")
    if fng is not None:
        bar_line("Fear & Greed", f"{float(fng.iloc[-1]):.0f}")
    ry = load("fred_real_yield10y", col="value")
    if ry is not None:
        bar_line("10y real yield", f"{ry.iloc[-1]:.2f}%")

    # ----------------------------------------------------------------- levels
    print("\n[7] LEVELS THAT MATTER (the switches)")
    bar_line("200d MA (regime flip level)", f"${ma200.iloc[-1]:,.2f}",
             f"{(ma200.iloc[-1]/px.iloc[-1]-1)*100:+.1f}% from spot")
    if btc is not None:
        alt = btc.reindex(px.index, method="ffill")
        ratio = (px / alt).dropna()
        bar_line("SOL/BTC 200d MA", f"{ratio.rolling(200).mean().iloc[-1]:.6f}",
                 f"spot {(ratio.rolling(200).mean().iloc[-1]/ratio.iloc[-1]-1)*100:+.1f}% away")
    bar_line("ATH (close basis)", f"${ath:,.2f}", f"{ath_date:%Y-%m-%d}")
    bar_line("cycle low (post-2021 bear)", f"${px.loc['2022-11-01':'2023-01-31'].min():,.2f}")
    print("\n  Provisional-bar rule: today's daily bar keeps moving until the UTC close;")
    print("  anything decided on it can un-decide itself. Weekly reads use closed weeks only.")


if __name__ == "__main__":
    main()
