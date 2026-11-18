#!/usr/bin/env python3
"""
ASSET TAPE - the raw numbers behind a regime read, for any onboarded asset.

One implementation, one config per asset (SOL, ZEC). The verdict itself lives in the
per-asset regime engine (strategies/sol_macro_regime.py); this file is the tape:
daily and weekly history, volume, relative strength, dominance, chain or supply
economics, derivatives positioning, the shared macro backdrop and the switch levels.

Conventions:
  - Price: the asset's committed longest series. Weekly bars are a deterministic
    resample of the daily closes that END on Sunday (Mon-Sun week), never a second
    source: price keeps one source of truth.
  - Every change window is calendar-anchored (days), never a row offset - Solana's
    stablecoin chart and Zcash's supply chart are both sparse in places.
  - The newest daily bar is labelled PROVISIONAL: it is still forming and becomes
    final at the next UTC close.
  - Weekly moving averages are named by their DAY equivalent: 28w = 196d, 7w = 49d.
  - A traded cross (when a venue lists it) is shown next to the ratio computed from
    USD closes; the gap between them is a venue basis, not an error.

Usage:
    ./.venv/bin/python strategies/asset_tape.py --asset SOL
    ./.venv/bin/python strategies/asset_tape.py --asset ZEC

Stateless: prints to stdout, saves nothing.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"


# --------------------------------------------------------------------------- helpers
def load(name, date_col="date", col="close"):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return pd.to_numeric(df[col], errors="coerce") if col in df.columns else df


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def chg(s, days):
    if s is None or len(s) < 2:
        return float("nan")
    base = s.loc[:s.index[-1] - pd.Timedelta(days=days)]
    if base.empty:
        return float("nan")
    return float((s.iloc[-1] / base.iloc[-1] - 1) * 100)


def weekly(daily):
    w = daily.resample("W-SUN").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    return w.dropna(subset=["close"])


def pct_rank_last(s, years=2):
    hist = s.loc[s.index[-1] - pd.Timedelta(days=365 * years):]
    if len(hist) < 30:
        return float("nan")
    return float((hist <= s.iloc[-1]).mean() * 100)


def money(v):
    if v != v:
        return "n/a"
    if abs(v) >= 1e9:
        return f"${v/1e9:,.2f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:,.1f}M"
    if abs(v) >= 1e3:
        return f"${v/1e3:,.0f}K"
    return f"${v:,.0f}"


def bar_line(label, value, note=""):
    print(f"  {label:<34} {value:>28}   {note}")


# ------------------------------------------------------- asset-specific extras blocks
def solana_extras(px, ctx):
    print("\n[4] SOLANA CHAIN ECONOMICS (DefiLlama, keyless)")
    for name, col, label in (
        ("sol_tvl_defillama", "tvl_usd", "chain TVL"),
        ("sol_stablecoins_defillama", "usd", "stablecoin supply"),
        ("sol_fees_defillama", "fees_usd", "chain fees"),
        ("sol_fees_defillama", "revenue_usd", "chain revenue"),
    ):
        s = load(name, col=col)
        if s is None:
            continue
        s = s.dropna()
        bar_line(f"{label} (latest)", money(s.iloc[-1]), f"7d avg {money(s.tail(7).mean())}")
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
            bar_line("DEX volume / TVL (7d)", f"{(d.tail(7).mean()/tvl.dropna().iloc[-1]):.2f}x",
                     "venue turnover; >1x is a hot retail tape")


def zcash_extras(px, ctx):
    """ZEC has no DeFi to measure: the fundamentals are issuance, supply and adoption."""
    print("\n[4] ZCASH SUPPLY AND ISSUANCE (CMC circulating supply, keyless)")
    mc = load("zec_mcap_cmc", col="mcap_usd")
    sup = load("zec_mcap_cmc", col="supply")
    if sup is not None:
        sup = sup[sup > 0].dropna()
        for back, label in ((365, "12m"), (180, "6m")):
            cut = sup.loc[:sup.index[-1] - pd.Timedelta(days=back)]
            if len(cut):
                bar_line(f"supply growth {label}", f"{(sup.iloc[-1]/cut.iloc[-1]-1)*100:+.2f}%",
                         f"{cut.iloc[-1]/1e6:,.2f}M -> {sup.iloc[-1]/1e6:,.2f}M ZEC")
        # Supply only ever rises; any downward step in the CMC series is a revision, not
        # a burn. The running maximum is the series to read for supply and dilution.
        clean = sup.cummax()
        bar_line("circulating supply", f"{clean.iloc[-1]/1e6:,.3f}M ZEC",
                 f"of the 21M cap: {(clean.iloc[-1]/21e6)*100:.1f}% issued")
        bar_line("block reward now", "3.125 ZEC/block",
                 "halved 2024-11; next halving due around 2028")
    if mc is not None:
        mc = mc.dropna()
        bar_line("market cap", money(mc.iloc[-1]), f"30d {chg(mc, 30):+.1f}% / 90d {chg(mc, 90):+.1f}%")
    # Structure that matters for a coin that just ran: where the move started.
    low_3y = px.loc[px.index[-1] - pd.Timedelta(days=365 * 3):].min()
    low_d = px.loc[px.index[-1] - pd.Timedelta(days=365 * 3):].idxmin()
    bar_line("3y low", f"${low_3y:,.2f}  ({low_d:%Y-%m-%d})",
             f"now {px.iloc[-1]/low_3y:.1f}x from that low")


ASSETS = {
    "SOL": {
        "name": "Solana",
        "price": ("solusd_daily_yahoo", "ts"),
        "venue": ("solusd_daily_okx", "ts", "OKX SOL-USDT"),
        "cross": ("btcusd_daily_bitstamp", "ts"),          # relative strength vs BTC
        "traded_cross": ("solbtc_daily_okx", "ts", "SOL/BTC"),
        "dominance": ("sol_dominance", "pct", "SOL.D"),
        "extras": solana_extras,
        "deriv": "sol",
        "launch_note": "2020-04-10 (SOL spot opened)",
        "ath_from": None,            # no launch artifact
        "vol_is_usd": True,          # Yahoo reports USD notional
    },
    "ZEC": {
        "name": "Zcash",
        "price": ("zecusd_daily_bitfinex", "ts"),
        "venue": ("zecusd_daily_okx", "ts", "OKX ZEC-USDT (listed 2025-11)"),
        "cross": ("btcusd_daily_bitstamp", "ts"),
        "traded_cross": ("zecbtc_daily_bitfinex", "ts", "ZEC/BTC"),
        "dominance": ("zec_dominance", "pct", "ZEC.D"),
        "extras": zcash_extras,
        "deriv": "zec",
        "launch_note": "2016-10-29 (ZEC launched 2016-10-28)",
        # ZEC's first two days printed 3,591 (close) and 20,000 (high) on slow-start supply.
        # Every ATH/drawdown read starts here instead, otherwise the whole history looks "deep".
        "ath_from": "2017-01-01",
        "vol_is_usd": False,         # Bitfinex reports BASE units (ZEC)
    },
}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Raw tape for an onboarded asset.")
    ap.add_argument("--asset", default="SOL", choices=sorted(ASSETS))
    args = ap.parse_args(argv)
    cfg = ASSETS[args.asset]
    label = args.asset

    name, tcol = cfg["price"]
    px = load(name, tcol)
    if px is None:
        raise SystemExit(f"{name}.csv missing - run build_macro_dataset.py --{label.lower()}-only")
    px = px.dropna()
    px = px[~px.index.duplicated(keep="last")].sort_index()

    now = datetime.now(timezone.utc)
    today = px.index[-1]
    btc = load(cfg["cross"][0], cfg["cross"][1])
    eth = load("ethusd_daily_bitstamp", "ts")

    ma50, ma200 = px.rolling(50).mean(), px.rolling(200).mean()
    # The reference window for ATH-family reads: ZEC's launch prints are an artifact.
    ref = px.loc[cfg["ath_from"]:] if cfg["ath_from"] else px
    ath, ath_date = ref.max(), ref.idxmax()
    dd = (px.iloc[-1] / ath - 1) * 100
    vol30 = np.log(px).diff().rolling(30).std() * np.sqrt(365) * 100

    print("=" * 84)
    print(f"{label} TAPE   {today:%Y-%m-%d} UTC   "
          f"(daily bar {'PROVISIONAL' if today.date() == now.date() else 'final'})")
    print("=" * 84)
    print(f"history        {px.index[0]:%Y-%m-%d} -> {px.index[-1]:%Y-%m-%d}   "
          f"{len(px)} daily closes, {len(weekly(px))} weekly closes   [{cfg['launch_note']}]")
    vname, vtcol, vlabel = cfg["venue"]
    venue = load(vname, vtcol)
    if venue is not None and len(venue):
        bar_line(f"cross-check ({vlabel})", f"${venue.iloc[-1]:,.2f}",
                 f"vs ${px.iloc[-1]:,.2f} ({(venue.iloc[-1]/px.iloc[-1]-1)*100:+.2f}% basis)")
        vq = load(vname, vtcol, "volume_usd")
        if vq is not None and len(vq.dropna()) > 30:
            vq = vq.dropna()
            bar_line(f"volume 30d avg ({vlabel.split(' ')[0]})", money(vq.tail(30).mean()),
                     f"vs 90d {money(vq.tail(90).mean())} ({(vq.tail(30).mean()/vq.tail(90).mean()):.2f}x)")

    # ------------------------------------------------------------------ daily tape
    print("\n[1] DAILY TAPE")
    bar_line("close", f"${px.iloc[-1]:,.2f}")
    for d, lbl in ((1, "1d"), (7, "7d"), (30, "30d"), (90, "90d"), (365, "1y")):
        bar_line(f"change {lbl}", f"{chg(px, d):+.1f}%")
    hi = load(name, tcol, "high")
    hi_ref = hi.loc[cfg["ath_from"]:] if (hi is not None and cfg["ath_from"]) else hi
    hi_ath = float(hi_ref.max()) if hi is not None else float("nan")
    bar_line("ATH (close basis)", f"${ath:,.2f}  ({ath_date:%Y-%m-%d})")
    bar_line("ATH (intraday high)", f"${hi_ath:,.2f}  ({hi.idxmax():%Y-%m-%d})" if hi is not None else "n/a")
    bar_line("drawdown from ATH", f"{dd:+.1f}%")
    bar_line("50d MA", f"${ma50.iloc[-1]:,.2f}  ({(px.iloc[-1]/ma50.iloc[-1]-1)*100:+.1f}%)")
    bar_line("200d MA", f"${ma200.iloc[-1]:,.2f}  ({(px.iloc[-1]/ma200.iloc[-1]-1)*100:+.1f}%)")
    bar_line("200d MA slope 30d", f"{(ma200.iloc[-1]/ma200.iloc[-31]-1)*100:+.2f}%")
    bar_line("RSI(14) daily", f"{rsi(px).iloc[-1]:.1f}")
    bar_line("realized vol 30d (ann.)", f"{vol30.iloc[-1]:.0f}%")
    last90 = px.loc[px.index[-1] - pd.Timedelta(days=90):]
    bar_line("90d high / low", f"${last90.max():,.2f} / ${last90.min():,.2f}")
    vol = load(name, tcol, "volume")
    if vol is not None:
        # Bitfinex quotes volume in the BASE asset; Yahoo quotes USD notional.
        vol_usd = vol * px.reindex(vol.index, method="ffill") if not cfg["vol_is_usd"] else vol
        v30, v90 = vol_usd.tail(30).mean(), vol_usd.tail(90).mean()
        bar_line("volume 30d avg", money(v30),
                 f"vs 90d {money(v90)} ({(v30/v90):.2f}x){'' if cfg['vol_is_usd'] else ' [base x close]'}")

    # ----------------------------------------------------------------- weekly tape
    print("\n[2] WEEKLY TAPE (resampled from the same daily closes, weeks end Sunday)")
    w = weekly(px)
    wma7, wma28 = w["close"].rolling(7).mean(), w["close"].rolling(28).mean()
    partial = "  [IN PROGRESS week]" if (now - w.index[-1]).days < 7 else ""
    bar_line("last weekly close", f"${w['close'].iloc[-1]:,.2f}  (week ending {w.index[-1]:%Y-%m-%d}){partial}")
    bar_line("weekly change", f"{chg(w['close'], 7):+.1f}%")
    bar_line("7w MA (49d)", f"${wma7.iloc[-1]:,.2f}  ({(w['close'].iloc[-1]/wma7.iloc[-1]-1)*100:+.1f}%)")
    bar_line("28w MA (196d)", f"${wma28.iloc[-1]:,.2f}  ({(w['close'].iloc[-1]/wma28.iloc[-1]-1)*100:+.1f}%)")
    bar_line("RSI(14) weekly", f"{rsi(w['close']).iloc[-1]:.1f}")
    up = int((w["close"].diff() > 0).iloc[::-1].cumprod().sum())
    dn = int((w["close"].diff() < 0).iloc[::-1].cumprod().sum())
    bar_line("weekly closes in a row", f"{up} up / {dn} down")
    print("\n  last 12 weekly closes:")
    for d, r in w.tail(12).iterrows():
        prev = w["close"].shift(1).loc[d]
        mark = "up  " if r["close"] > r["open"] else "down"
        print(f"    {d:%Y-%m-%d}  open ${r['open']:>9,.2f}  close ${r['close']:>9,.2f}  "
              f"high ${r['high']:>9,.2f}  low ${r['low']:>9,.2f}  {mark} "
              f"{((r['close']/prev)-1)*100:+.1f}%")

    # ---------------------------------------------------------------- relative
    print(f"\n[3] RELATIVE STRENGTH, {cfg['dominance'][2]} AND MARKET-SHARE CONTEXT")
    for other, other_name in ((btc, "BTC"), (eth, "ETH")):
        if other is None:
            continue
        alt = other.reindex(px.index, method="ffill")
        ratio = (px / alt).dropna()
        ma = ratio.rolling(200).mean()
        bar_line(f"{label}/{other_name} (from USD closes)", f"{ratio.iloc[-1]:.6f}",
                 f"200d MA {ma.iloc[-1]:.6f} ({(ratio.iloc[-1]/ma.iloc[-1]-1)*100:+.1f}%), "
                 f"90d {chg(ratio, 90):+.1f}%, "
                 f"from peak {(ratio.iloc[-1]/ratio.loc[cfg['ath_from']:].max()-1)*100:+.1f}%")
    tc_name, tc_col, tc_label = cfg["traded_cross"]
    tc = load(tc_name, tc_col)
    if tc is not None and btc is not None:
        vt = pd.Series(tc.values, index=tc.index.normalize() + pd.Timedelta(days=1))
        implied = (px / btc.reindex(px.index, method="ffill")).dropna()
        j = pd.concat({"venue": vt, "implied": implied}, axis=1).dropna()
        if len(j) > 2:
            j = j.iloc[:-1]
            basis = ((j["venue"] / j["implied"] - 1) * 100).tail(30)
            bar_line(f"{tc_label} venue vs USD-implied", f"median basis {basis.median():+.2f}%",
                     f"{len(basis)} complete days, range {basis.min():+.2f}% to {basis.max():+.2f}%")

    dname, dcol, dlabel = cfg["dominance"]
    dom = load(dname, col=dcol)      # not the date column: (name, col) order bites
    if dom is not None:
        dom = dom.dropna()
        dm200 = float(dom.rolling(200).mean().iloc[-1])
        bar_line(f"{dlabel} dominance", f"{dom.iloc[-1]:.2f}%",
                 f"200d MA {dm200:.2f}%, 30d {chg(dom, 30):+.1f}%, 90d {chg(dom, 90):+.1f}%")
        bar_line(f"  {dlabel} all-time peak", f"{dom.max():.2f}%  ({dom.idxmax():%Y-%m-%d})",
                 f"now {(dom.iloc[-1]/dom.max()-1)*100:+.1f}% from that peak")
        bar_line(f"  {dlabel} 2y percentile", f"{pct_rank_last(dom):.0f}",
                 "share of sessions at or below today")
    tot = load("cmc_total_mcap", col="total_mcap_usd")
    if tot is not None:
        bar_line("total crypto market cap", f"${tot.iloc[-1]/1e12:,.2f}T", f"30d {chg(tot, 30):+.1f}%")
    btcd = load("cmc_total_mcap", col="btc_dominance")
    ethd = load("cmc_total_mcap", col="eth_dominance")
    if btcd is not None:
        bar_line("BTC / ETH dominance", f"{btcd.iloc[-1]:.1f}% / {ethd.iloc[-1]:.1f}%",
                 "the shares this asset is competing against")

    # -------------------------------------------------------------- extras block
    cfg["extras"](px, {})

    # ------------------------------------------------------------ derivatives
    p = cfg["deriv"]
    print(f"\n[5] DERIVATIVES POSITIONING (Binance USD-M archive, {label}USDT)")
    oi = load(f"bn_oi_{p}", col="value")
    if oi is not None:
        oi = oi.dropna()
        oi_usd = oi * px.reindex(oi.index, method="ffill")
        bar_line("open interest", f"{oi.iloc[-1]/1e6:,.2f}M {label}",
                 f"{money(oi_usd.iloc[-1])} at close")
        bar_line("  OI 30d change", f"{chg(oi_usd, 30):+.1f}% (USD)",
                 f"2y percentile {pct_rank_last(oi_usd):.0f}")
    fund = load(f"bn_funding_{p}", col="value")
    if fund is not None:
        f = fund.dropna()
        bar_line("funding (daily sum, last)", f"{f.iloc[-1]*100:+.4f}%",
                 f"7d {f.tail(7).sum()*100:+.4f}%  30d {f.tail(30).sum()*100:+.4f}%")
        bar_line("  funding 90d mean", f"{f.tail(90).mean()*100:+.4f}%/day",
                 "positive = longs paying (crowded long)")
    lsr = load(f"bn_lsr_{p}", col="value")
    if lsr is not None:
        l = lsr.dropna()
        bar_line("top-trader long/short", f"{l.iloc[-1]:.3f}",
                 f"30d ago {l.loc[:l.index[-1]-pd.Timedelta(days=30)].iloc[-1]:.3f}")
    taker = load(f"bn_taker_{p}", col="value")
    if taker is not None:
        t = taker.dropna()
        bar_line("taker buy/sell (last)", f"{t.iloc[-1]:.3f}", f"30d mean {t.tail(30).mean():.3f}")

    # ------------------------------------------------------------ macro backdrop
    print("\n[6] SHARED MACRO BACKDROP (the same inputs the BTC/ETH/SOL engines read)")
    dxy = load("dxy")
    if dxy is not None:
        m = dxy.rolling(200).mean().iloc[-1]
        bar_line("DXY", f"{dxy.iloc[-1]:.2f}",
                 f"200d MA {m:.2f} ({'firm - headwind' if dxy.iloc[-1] > m else 'soft - tailwind'})")
    u10, u3m = load("us10y"), load("us3m")
    if u10 is not None and u3m is not None:
        curve = (u10 - u3m.reindex(u10.index).ffill()).dropna()
        base = curve.loc[:curve.index[-1] - pd.Timedelta(days=90)]
        bar_line("10y-3m curve", f"{curve.iloc[-1]:+.2f}%",
                 f"90d ago {base.iloc[-1]:+.2f}%" if len(base) else "")
    m2 = load("fred_us_m2", col="value")
    if m2 is not None:
        base = m2.loc[:m2.index[-1] - pd.Timedelta(days=365)]
        bar_line("US M2 YoY", f"{(m2.iloc[-1]/base.iloc[-1]-1)*100:+.1f}%", f"level {m2.iloc[-1]:,.0f}")
    stab = load("stablecoin_total_liquidity", col="total_cap_usd")
    if stab is not None:
        bar_line("total stablecoin cap", f"${stab.iloc[-1]/1e9:,.1f}B", f"30d {chg(stab, 30):+.1f}%")
    vix = load("vix")
    if vix is not None:
        bar_line("VIX", f"{vix.iloc[-1]:.1f}")
    spx = load("sp500")
    if spx is not None:
        bar_line("SPX", f"{spx.iloc[-1]:,.0f}", f"200d MA {spx.rolling(200).mean().iloc[-1]:,.0f}")
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
        ratio = (px / btc.reindex(px.index, method="ffill")).dropna()
        rma = ratio.rolling(200).mean().iloc[-1]
        bar_line(f"{label}/BTC 200d MA", f"{rma:.6f}",
                 f"spot {(rma/ratio.iloc[-1]-1)*100:+.1f}% away")
    bar_line("ATH", f"${ath:,.2f}", f"{ath_date:%Y-%m-%d}")
    three_y = px.loc[px.index[-1] - pd.Timedelta(days=365 * 3):]
    bar_line("3y high / low", f"${three_y.max():,.2f} / ${three_y.min():,.2f}",
             f"low {three_y.idxmin():%Y-%m-%d}, now {px.iloc[-1]/three_y.min():.1f}x that low")
    print("\n  Provisional-bar rule: today's daily bar keeps moving until the UTC close;")
    print("  anything decided on it can un-decide itself. Weekly reads use closed weeks only.")


if __name__ == "__main__":
    main()
