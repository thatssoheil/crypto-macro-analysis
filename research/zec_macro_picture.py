#!/usr/bin/env python3
"""
ZEC MACRO PICTURE - PNG renderer (owner-facing charts for the Zcash onboarding).

Reads the committed dataset only (data/macro_dataset/), writes PNGs to the output
directory given on the command line, prints what it wrote.

Run with the MICRO venv (the macro venv has no matplotlib):

    /root/hermes-projects/products/crypto-micro-analysis/.venv/bin/python \
        research/zec_macro_picture.py ~/hermes-dump/zec-onboarding-2026-11-18

Charts:
  01 weekly close + 7w/28w MA (log, from 2017)     05 derivatives positioning
  02 daily close + 50/200 DMA (log)                06 liquidation map (model)
  03 ZEC/BTC, ZEC/ETH, ZEC.D                       07 drawdown from the post-launch ATH
  04 supply, issuance and market cap

Note on the launch artifact: ZEC's first two sessions printed 3,591 (close) and 20,000
(intraday) on slow-start supply. Charts and drawdowns start 2017-01-01 unless the panel
is explicitly about the full raw history.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "macro_dataset"
START = pd.Timestamp("2017-01-01", tz="UTC")

C_PRICE = "#1f6feb"
C_ALT = "#d29922"
C_RED = "#c0392b"
C_GREEN = "#1e8449"
C_GREY = "#6e6e6e"
C_PURPLE = "#6b46c1"


def load(name, date_col="date", col="close"):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return df


def style(ax, title, ylabel=None):
    ax.set_title(title, fontsize=11, fontweight="bold", loc="left", pad=8)
    ax.grid(alpha=0.25, linewidth=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=9)
    ax.tick_params(labelsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def save(fig, out_dir, name):
    path = out_dir / name
    fig.savefig(path, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  wrote {path}")


def main():
    out_dir = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "hermes-dump" / "zec-onboarding"
    out_dir.mkdir(parents=True, exist_ok=True)

    px = load("zecusd_daily_bitfinex", "ts").dropna()
    px = px[~px.index.duplicated(keep="last")].sort_index()
    hi = load("zecusd_daily_bitfinex", "ts", "high")
    btc = load("btcusd_daily_bitstamp", "ts")
    eth = load("ethusd_daily_bitstamp", "ts")
    ref = px.loc[START:]

    # ------------------------------------------------------------ 01 weekly
    w = ref.resample("W-SUN").last().dropna()
    fig, ax = plt.subplots(figsize=(13, 6.2), constrained_layout=True)
    ax.plot(w.index, w.values, color=C_PRICE, lw=1.6, label="weekly close (Mon-Sun)")
    ax.plot(w.index, w.rolling(7).mean(), color=C_ALT, lw=1.1, label="7w MA (49d)")
    ax.plot(w.index, w.rolling(28).mean(), color=C_RED, lw=1.1, label="28w MA (196d)")
    ath = float(ref.max())
    ax.axhline(ath, color=C_GREY, ls=":", lw=1)
    ax.annotate(f"post-launch ATH ${ath:,.0f}", xy=(w.index[-1], ath), xytext=(-8, 5),
                textcoords="offset points", ha="right", fontsize=8, color=C_GREY)
    ax.set_yscale("log")
    ax.get_yaxis().set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.legend(fontsize=8, loc="upper left", frameon=False)
    style(ax, "ZEC weekly, 2017-01 -> 2026-11 (log; 2016 launch prints omitted)")
    save(fig, out_dir, "01_zec_weekly.png")

    # ------------------------------------------------------------ 02 daily + MAs
    ma50, ma200 = px.rolling(50).mean(), px.rolling(200).mean()
    d = px.loc[START:]
    fig, ax = plt.subplots(figsize=(13, 6.2), constrained_layout=True)
    ax.plot(d.index, d.values, color=C_PRICE, lw=1.0, label="daily close")
    ax.plot(d.index, ma50.loc[START:].values, color=C_ALT, lw=1.2, label="50d MA")
    ax.plot(d.index, ma200.loc[START:].values, color=C_RED, lw=1.4, label="200d MA (regime line)")
    above = d >= ma200.loc[START:]
    ax.fill_between(d.index, d.min() * 0.8, d.max() * 1.2, where=above, color=C_GREEN, alpha=0.06)
    ax.fill_between(d.index, d.min() * 0.8, d.max() * 1.2, where=~above, color=C_RED, alpha=0.05)
    ax.set_yscale("log")
    ax.get_yaxis().set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.legend(fontsize=8, loc="upper left", frameon=False, ncol=3)
    style(ax, "ZEC daily with the trend lines (log); shaded green = above the 200d")
    save(fig, out_dir, "02_zec_daily_ma.png")

    # ------------------------------------------------------------ 03 ratios + dominance
    dom = load("zec_dominance", col="pct")
    fig, axes = plt.subplots(3, 1, figsize=(13, 10.5), sharex=True, constrained_layout=True)
    for ax, other, label in ((axes[0], btc, "ZEC/BTC"), (axes[1], eth, "ZEC/ETH")):
        if other is None:
            continue
        alt = other.reindex(px.index, method="ffill")
        ratio = (px / alt).dropna().loc[START:]
        ax.plot(ratio.index, ratio.values, color=C_PRICE, lw=1.0, label=f"{label} from USD closes")
        ax.plot(ratio.index, ratio.rolling(200).mean(), color=C_RED, lw=1.2, label=f"{label} 200d MA")
        ax.set_yscale("log")
        style(ax, f"{label} against its 200d MA (log)")
        ax.legend(fontsize=8, loc="upper left", frameon=False)
    ax = axes[2]
    if dom is not None:
        dd_ = dom.dropna().loc[START:]
        ax.plot(dd_.index, dd_.values, color=C_PURPLE, lw=1.1, label="ZEC dominance (ZEC.D)")
        ax.plot(dd_.index, dd_.rolling(200).mean().loc[START:], color=C_RED, lw=1.1, label="200d MA")
        peak_i = dd_.idxmax()
        ax.annotate(f"peak {dd_.max():.2f}% ({peak_i:%Y-%m})", xy=(peak_i, dd_.max()),
                    xytext=(-10, 8), textcoords="offset points", fontsize=8.5, color="#111111",
                    ha="right", bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.75))
        ax.legend(fontsize=8, loc="upper left", frameon=False)
    style(ax, "ZEC.D: Zcash market cap as a share of the whole crypto market (%)", "%")
    save(fig, out_dir, "03_zec_ratios.png")

    # ------------------------------------------------------------ 04 supply + mcap
    # CMC's ZEC "circulating supply" has two defects: it steps (revisions) and it spikes
    # (a 10M print in 2017-18 that never happened). Supply cannot fall, so the cleaned
    # series is the running maximum; the YoY growth of that series is the inflation read.
    # No emission model is drawn: Zcash's block count and halving heights do not reconcile
    # from the free feeds, and a wrong supply curve is worse than none.
    sup = load("zec_mcap_cmc", col="supply")
    mc = load("zec_mcap_cmc", col="mcap_usd")
    fig, axes = plt.subplots(3, 1, figsize=(13, 9.4), sharex=True, constrained_layout=True)
    ax = axes[0]
    if mc is not None:
        m = mc.dropna()
        ax.plot(m.index, m.values / 1e9, color=C_PURPLE, lw=1.3, label="market cap (CMC)")
        ax.set_yscale("log")
        ax.legend(fontsize=8, loc="upper left", frameon=False)
    style(ax, "ZEC market cap (USD bn, log)", "USD bn")
    ax = axes[1]
    # CMC's ZEC supply is unusable before 2022: it carries a 10M spike in 2017-18 that
    # never happened, and the running-maximum trick would freeze that error into the line.
    sup_ok = sup.loc[pd.Timestamp("2022-01-01", tz="UTC"):] if sup is not None else None
    if sup_ok is not None:
        s_ = sup_ok[sup_ok > 0].dropna()
        clean = s_.cummax()
        ax.plot(s_.index, s_.values / 1e6, color=C_GREY, lw=0.7, alpha=0.6, label="CMC raw (steps and spikes)")
        ax.plot(clean.index, clean.values / 1e6, color=C_PRICE, lw=1.5, label="cleaned (running maximum)")
        ax.axhline(21, color=C_RED, ls=":", lw=1)
        ax.annotate("21M hard cap", xy=(clean.index[-1], 21), xytext=(-6, -10),
                    textcoords="offset points", ha="right", fontsize=8, color=C_RED)
        ax.legend(fontsize=8, loc="lower right", frameon=False)
    style(ax, "ZEC circulating supply (millions), 2022-01 onward: raw CMC vs monotone", "M ZEC")
    ax = axes[2]
    if sup_ok is not None:
        clean = sup_ok[sup_ok > 0].dropna().cummax()
        yoy = (clean / clean.shift(freq="365D") - 1).dropna() * 100
        yoy = yoy.loc[START:]
        ax.plot(yoy.index, yoy.values, color=C_GREEN, lw=1.3, label="supply growth, year over year")
        ax.legend(fontsize=8, loc="upper right", frameon=False)
        ax.annotate("the 2024 halving cuts issuance in half", xy=(pd.Timestamp("2024-11-20", tz="UTC"), float(yoy.median())),
                    xytext=(8, 0), textcoords="offset points", fontsize=8, color=C_GREY)
        ax.axvline(pd.Timestamp("2024-11-20", tz="UTC"), color=C_RED, ls="--", lw=0.9)
    style(ax, "ZEC dilution: supply growth year over year (%)", "%")
    save(fig, out_dir, "04_zec_supply.png")

    # ------------------------------------------------------------ 05 derivatives
    oi = load("bn_oi_zec", col="value")
    fund = load("bn_funding_zec", col="value")
    lsr = load("bn_lsr_zec", col="value")
    taker = load("bn_taker_zec", col="value")
    fig, axes = plt.subplots(4, 1, figsize=(13, 11.2), sharex=True, constrained_layout=True)
    ax = axes[0]
    if oi is not None:
        oi_usd = (oi * px.reindex(oi.index, method="ffill")).dropna() / 1e6
        ax.plot(oi_usd.index, oi_usd.values, color=C_PRICE, lw=0.9, label="Binance perp OI (USD)")
        ax.plot(oi_usd.index, oi_usd.rolling(30).mean(), color=C_ALT, lw=1.0, label="30d MA")
        ax.legend(fontsize=8, loc="upper left", frameon=False)
    style(ax, "Perp open interest, Binance USD-M (USD m)", "USD m")
    ax = axes[1]
    if fund is not None:
        f = fund.dropna() * 100
        ax.bar(f.index, f.values, width=1.0, color=np.where(f.values >= 0, C_GREEN, C_RED), alpha=0.5)
        ax.plot(f.index, f.rolling(30).mean(), color="#111111", lw=1.0, label="30d mean")
        ax.axhline(0, color=C_GREY, lw=0.8)
        ax.legend(fontsize=8, loc="upper left", frameon=False)
    style(ax, "Funding, daily sum of the prints (%/day; positive = longs pay)", "%/day")
    ax = axes[2]
    if lsr is not None:
        l = lsr.dropna()
        ax.plot(l.index, l.values, color=C_PRICE, lw=0.8, label="top-trader long/short")
        ax.plot(l.index, l.rolling(30).mean(), color=C_ALT, lw=1.0, label="30d MA")
        ax.axhline(1.0, color=C_GREY, lw=0.8)
        ax.legend(fontsize=8, loc="upper left", frameon=False)
    style(ax, "Top-trader long/short account ratio (Binance)", "ratio")
    ax = axes[3]
    if taker is not None:
        t = taker.dropna()
        ax.plot(t.index, t.values, color=C_PRICE, lw=0.8, label="taker buy/sell volume ratio")
        ax.plot(t.index, t.rolling(30).mean(), color=C_ALT, lw=1.0, label="30d MA")
        ax.axhline(1.0, color=C_GREY, lw=0.8)
        ax.legend(fontsize=8, loc="upper left", frameon=False)
    style(ax, "Taker buy/sell ratio (Binance)", "ratio")
    save(fig, out_dir, "05_zec_derivatives.png")

    # ------------------------------------------------------------ 06 liquidation map
    try:
        sys.path.insert(0, str(ROOT / "strategies"))
        import liquidity_map as lmap
        ldf = lmap.okx_candles(336, inst="ZEC-USDT-SWAP")
        oi_usd, oi_src = lmap.open_interest("ZEC")
        grid = lmap.build_grid(ldf, oi_usd, lmap.LEVERAGE_PROFILES["balanced"], 336)
        above, below = lmap.key_levels(grid)
        mat = np.array(grid["matrix"]) / 1e6
        lo_p, step = grid["lo"], grid["step"]
        hi_p = lo_p + mat.shape[1] * step
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(13.5, 5.8), constrained_layout=True,
                                     gridspec_kw={"width_ratios": [1.5, 1]})
        im = a1.imshow(mat, aspect="auto", origin="lower", extent=[0, mat.shape[0], lo_p, hi_p],
                       cmap="magma")
        a1.axhline(grid["spot"], color="white", lw=1.1, ls="--")
        a1.annotate(f"spot ${grid['spot']:,.2f}", xy=(1, grid["spot"]), xytext=(5, 4),
                    textcoords="offset points", color="white", fontsize=8)
        a1.set_xlabel("hours inside the 14-day cohort window (oldest -> now)", fontsize=9)
        a1.set_ylabel("price", fontsize=9)
        a1.set_title(f"Modelled liquidation heatmap, ZEC perps  (OI {oi_usd/1e6:,.0f}M, {oi_src})",
                     fontsize=10.5, fontweight="bold", loc="left")
        cb = fig.colorbar(im, ax=a1, fraction=0.035, pad=0.01)
        cb.set_label("USD m per 0.1% price bin", fontsize=8)
        cb.ax.tick_params(labelsize=7)
        lv = ([("short", l) for l in above] + [("long", l) for l in below])
        a2.barh([l["price"] for _, l in lv], [l["usd"] / 1e6 for _, l in lv],
                height=grid["spot"] * 0.005,
                color=[C_GREEN if side == "short" else C_RED for side, _ in lv], alpha=0.8)
        a2.axhline(grid["spot"], color="#111111", lw=1.0, ls="--")
        a2.set_title("Strongest modelled shelves (USD m)\ngreen above = short liqs, red below = long liqs",
                     fontsize=10, fontweight="bold", loc="left")
        a2.set_xlabel("USD m modelled", fontsize=9)
        a2.grid(alpha=0.25, linewidth=0.6)
        for side in ("top", "right"):
            a2.spines[side].set_visible(False)
        a2.tick_params(labelsize=8)
        save(fig, out_dir, "06_zec_liquidation_map.png")
    except Exception as exc:
        print(f"  WARN liquidity map chart skipped: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------ 07 drawdown
    ath_run = ref.cummax()
    ddv = (ref / ath_run - 1) * 100
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 7.2), sharex=True,
                                 gridspec_kw={"height_ratios": [2, 1]}, constrained_layout=True)
    a1.plot(ref.index, ref.values, color=C_PRICE, lw=1.0)
    a1.plot(ath_run.index, ath_run.values, color=C_GREY, lw=0.8, ls="--", label="running ATH")
    a1.set_yscale("log")
    a1.get_yaxis().set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    a1.legend(fontsize=8, frameon=False, loc="upper left")
    style(a1, "ZEC price and its running all-time high (post-launch window)")
    a2.fill_between(ddv.index, ddv.values, 0, color=C_RED, alpha=0.35)
    a2.plot(ddv.index, ddv.values, color=C_RED, lw=0.8)
    a2.annotate(f"now {ddv.iloc[-1]:.1f}%", xy=(ddv.index[-1], ddv.iloc[-1]),
                xytext=(-6, -12), textcoords="offset points", ha="right", fontsize=9, color=C_RED)
    style(a2, "Drawdown from the running ATH (%)")
    save(fig, out_dir, "07_zec_drawdown.png")

    print(f"\nDONE. charts in {out_dir}")


if __name__ == "__main__":
    main()
