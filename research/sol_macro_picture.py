#!/usr/bin/env python3
"""
SOL MACRO PICTURE - PNG renderer (owner-facing charts for the Solana onboarding).

Reads the committed dataset only (data/macro_dataset/), writes PNGs to the output
directory given on the command line, prints what it wrote. Nothing else is saved.

Run with the MICRO venv (the macro venv has no matplotlib):

    /root/hermes-projects/products/crypto-micro-analysis/.venv/bin/python \
        research/sol_macro_picture.py ~/hermes-dump/solana-onboarding-2026-11-18

Charts:
  01 weekly close + 7w/28w MA (log)          06 derivatives positioning
  02 daily close + 50/200 DMA (log)          07 shared macro backdrop
  03 drawdown from ATH                       08 liquidation map (model)
  04 SOL/BTC and SOL/ETH vs 200d MA          09 composite score history
  05 chain economics (TVL/stables/DEX/fees)

Conventions: weekly bars end on Sunday, MAs are labelled by their day equivalent
(28w = 196d), all price axes are log, and the newest daily bar is marked provisional.
"""
import json
import subprocess
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
PY = str(ROOT / ".venv" / "bin" / "python")

C_PRICE = "#1f6feb"
C_ALT = "#d29922"
C_RED = "#c0392b"
C_GREEN = "#1e8449"
C_GREY = "#6e7681"
C_FILL = "#8fb8f0"


def load(name, date_col="date", col="close"):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")   # blank cells become NaN, not strings
    return df.apply(pd.to_numeric, errors="ignore")


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


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
    return path


def main():
    out_dir = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "hermes-dump" / "solana-onboarding"
    out_dir.mkdir(parents=True, exist_ok=True)

    px = load("solusd_daily_yahoo", "ts").dropna()
    hi, lo, vol = (load("solusd_daily_yahoo", "ts", c) for c in ("high", "low", "volume"))
    btc = load("btcusd_daily_bitstamp", "ts")
    eth = load("ethusd_daily_bitstamp", "ts")

    # ------------------------------------------------------------ 01 weekly
    w = px.resample("W-SUN").last().dropna()
    fig, ax = plt.subplots(figsize=(13, 6.2), constrained_layout=True)
    ax.plot(w.index, w.values, color=C_PRICE, lw=1.6, label="weekly close (Mon-Sun)")
    ax.plot(w.index, w.rolling(7).mean(), color=C_ALT, lw=1.1, label="7w MA (49d)")
    ax.plot(w.index, w.rolling(28).mean(), color=C_RED, lw=1.1, label="28w MA (196d)")
    ax.axhline(float(hi.max()), color=C_GREY, ls=":", lw=1)
    ax.annotate(f"ATH intraday ${float(hi.max()):,.2f}", xy=(w.index[-1], float(hi.max())),
                xytext=(-8, 4), textcoords="offset points", ha="right", fontsize=8, color=C_GREY)
    ax.set_yscale("log")
    ax.set_yticks([0.5, 1, 2, 5, 10, 20, 50, 100, 200, 300])
    ax.get_yaxis().set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:g}"))
    ax.legend(fontsize=8, loc="upper left", frameon=False)
    style(ax, "SOL weekly, full history (2020-04 -> 2026-11, log scale)")
    save(fig, out_dir, "01_sol_weekly.png")

    # ------------------------------------------------------------ 02 daily + MAs
    ma50, ma200 = px.rolling(50).mean(), px.rolling(200).mean()
    fig, ax = plt.subplots(figsize=(13, 6.2), constrained_layout=True)
    ax.plot(px.index, px.values, color=C_PRICE, lw=1.0, label="daily close")
    ax.plot(ma50.index, ma50.values, color=C_ALT, lw=1.2, label="50d MA")
    ax.plot(ma200.index, ma200.values, color=C_RED, lw=1.4, label="200d MA (regime line)")
    above = px >= ma200
    ax.fill_between(px.index, px.min() * 0.8, px.max() * 1.2, where=above,
                    color=C_GREEN, alpha=0.06, label="above 200d (risk-on side)")
    ax.fill_between(px.index, px.min() * 0.8, px.max() * 1.2, where=~above & ma200.notna(),
                    color=C_RED, alpha=0.05, label="below 200d (cash side)")
    ax.set_yscale("log")
    ax.get_yaxis().set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:g}"))
    ax.legend(fontsize=8, loc="upper left", frameon=False, ncol=2)
    style(ax, "SOL daily with the two trend lines that decide the regime (log)")
    save(fig, out_dir, "02_sol_daily_ma.png")

    # ------------------------------------------------------------ 03 drawdown
    ath_run = px.cummax()
    dd = (px / ath_run - 1) * 100
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 7.2), sharex=True,
                                 gridspec_kw={"height_ratios": [2, 1]}, constrained_layout=True)
    a1.plot(px.index, px.values, color=C_PRICE, lw=1.0)
    a1.plot(ath_run.index, ath_run.values, color=C_GREY, lw=0.8, ls="--", label="running ATH")
    a1.set_yscale("log")
    a1.get_yaxis().set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:g}"))
    a1.legend(fontsize=8, frameon=False, loc="upper left")
    style(a1, "SOL price and its running all-time high")
    a2.fill_between(dd.index, dd.values, 0, color=C_RED, alpha=0.35)
    a2.plot(dd.index, dd.values, color=C_RED, lw=0.8)
    for lvl in (-20, -50, -80):
        a2.axhline(lvl, color=C_GREY, ls=":", lw=0.8)
    a2.annotate(f"now {dd.iloc[-1]:.1f}%", xy=(dd.index[-1], dd.iloc[-1]),
                xytext=(-6, -12), textcoords="offset points", ha="right", fontsize=9, color=C_RED)
    style(a2, "Drawdown from the running ATH (%)")
    save(fig, out_dir, "03_sol_drawdown.png")

    # ------------------------------------------------------------ 04 ratios + SOL.D
    dom = load("sol_dominance", col="pct")
    venue = load("solbtc_daily_okx", "ts")
    fig, axes = plt.subplots(3, 1, figsize=(13, 10.5), sharex=True, constrained_layout=True)
    for ax, other, label in ((axes[0], btc, "SOL/BTC"), (axes[1], eth, "SOL/ETH")):
        if other is None:
            continue
        alt = other.reindex(px.index, method="ffill")
        ratio = (px / alt).dropna()
        ax.plot(ratio.index, ratio.values, color=C_PRICE, lw=1.0, label=f"{label} from USD closes")
        ax.plot(ratio.index, ratio.rolling(200).mean(), color=C_RED, lw=1.3, label=f"{label} 200d MA")
        ax.set_yscale("log")
        style(ax, f"{label} against its 200d MA (log)")
        ax.legend(fontsize=8, frameon=False, loc="upper left")
    ax = axes[2]
    if dom is not None:
        ax.plot(dom.index, dom.values, color=C_PRICE, lw=1.0, label="SOL dominance (SOL.D)")
        ax.plot(dom.index, dom.rolling(200).mean(), color=C_RED, lw=1.1, label="200d MA")
        peak_i = dom.idxmax()
        ax.annotate(f"peak {dom.max():.2f}% ({peak_i:%Y-%m})", xy=(peak_i, dom.max()),
                    xytext=(-10, 8), textcoords="offset points", fontsize=8.5,
                    color="#111111", ha="right",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.75))
        ax.legend(fontsize=8, frameon=False, loc="upper left")
    style(ax, "SOL.D: Solana market cap as a share of the whole crypto market (%)", "%")
    save(fig, out_dir, "04_sol_ratios.png")

    # ------------------------------------------------------------ 05 chain economics
    tvl = load("sol_tvl_defillama", col="tvl_usd")
    stab = load("sol_stablecoins_defillama", col="usd")
    dex = load("sol_dex_volume_defillama", col="usd")
    fees = load("sol_fees_defillama", col="fees_usd")
    rev = load("sol_fees_defillama", col="revenue_usd")

    fig, axes = plt.subplots(4, 1, figsize=(13, 11.5), sharex=True, constrained_layout=True)
    ax = axes[0]
    ax.plot(tvl.index, tvl.values / 1e9, color=C_PRICE, lw=1.0, label="chain TVL")
    ax.plot(tvl.index, tvl.rolling(60).mean() / 1e9, color=C_ALT, lw=1.0, label="60d MA")
    ax.set_yscale("log")
    style(ax, "Solana chain TVL (USD, log)", "USD bn")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    ax = axes[1]
    # DefiLlama's 2021 points are quarterly snapshots (the first one is $8.7k, an
    # artifact, not a real reading) - plot from 2022 where the series is daily.
    st = stab[stab.index >= pd.Timestamp("2022-01-01", tz="UTC")]
    ax.plot(st.index, st.values / 1e9, color=C_GREEN, lw=1.0, label="stablecoin supply on Solana")
    ax.set_yscale("log")
    style(ax, "Stablecoin supply minted on Solana (USD, log; daily data from 2022)", "USD bn")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    ax = axes[2]
    # first month of the DefiLlama DEX series is warmup junk ($3, $100, $42k)
    dex = dex[dex.index >= pd.Timestamp("2021-11-01", tz="UTC")]
    ax.plot(dex.index, dex.values / 1e9, color=C_GREY, lw=0.6, alpha=0.6, label="daily DEX volume")
    ax.plot(dex.index, dex.rolling(7).mean() / 1e9, color=C_PRICE, lw=1.1, label="7d MA")
    ax.set_yscale("log")
    style(ax, "DEX volume on Solana (USD/day, log)", "USD bn/day")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    ax = axes[3]
    ax.plot(fees.index, fees.rolling(7).mean() / 1e6, color=C_ALT, lw=1.1, label="chain fees 7d MA")
    if rev is not None:
        ax.plot(rev.index, rev.rolling(7).mean() / 1e6, color=C_RED, lw=1.1, label="chain revenue 7d MA (burned)")
    ax.set_yscale("log")
    style(ax, "Chain fees and revenue (USD/day, log)", "USD m/day")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    save(fig, out_dir, "05_solana_chain_economics.png")

    # ------------------------------------------------------------ 06 derivatives
    oi = load("bn_oi_sol", col="value")
    fund = load("bn_funding_sol", col="value")
    lsr = load("bn_lsr_sol", col="value")
    taker = load("bn_taker_sol", col="value")
    dvol = load("dvol_sol", col="value")

    fig, axes = plt.subplots(4, 1, figsize=(13, 11.5), sharex=True, constrained_layout=True)
    ax = axes[0]
    if oi is not None:
        oi_usd = (oi * px.reindex(oi.index, method="ffill")).dropna() / 1e9
        ax.plot(oi_usd.index, oi_usd.values, color=C_PRICE, lw=0.9, label="Binance perp OI (USD)")
        ax.plot(oi_usd.index, oi_usd.rolling(30).mean(), color=C_ALT, lw=1.0, label="30d MA")
        ax.legend(fontsize=8, frameon=False, loc="upper left")
    style(ax, "Perp open interest, Binance USD-M (USD bn)", "USD bn")
    ax = axes[1]
    if fund is not None:
        f = fund.dropna() * 100
        ax.bar(f.index, f.values, width=1.0, color=np.where(f.values >= 0, C_GREEN, C_RED), alpha=0.5)
        ax.plot(f.index, f.rolling(30).mean(), color="#111111", lw=1.0, label="30d mean")
        ax.axhline(0, color=C_GREY, lw=0.8)
        # Nov 2022: Binance moved SOLUSDT to 2-hour funding and pinned it at the -2 percent
        # cap, so the daily SUM ran to -20 percent/day and flattens everything else.
        # The axis is clipped and the spike is labelled instead of rescaling the panel.
        ax.set_ylim(-0.75, 0.75)
        ax.annotate("Nov 2022: 2h funding at the -2%/print cap\n(daily sum runs off this scale)",
                    xy=(pd.Timestamp("2022-11-10", tz="UTC"), -0.72), xytext=(12, 14),
                    textcoords="offset points", fontsize=7.5, color="#111111",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=C_GREY, lw=0.5, alpha=0.85))
        ax.legend(fontsize=8, frameon=False, loc="upper left")
    style(ax, "Funding, daily sum of the prints (%/day; positive = longs pay; y clipped)", "%/day")
    ax = axes[2]
    if lsr is not None:
        ax.plot(lsr.index, lsr.values, color=C_PRICE, lw=0.8, label="top-trader long/short")
        ax.plot(lsr.index, lsr.rolling(30).mean(), color=C_ALT, lw=1.0, label="30d MA")
        ax.axhline(1.0, color=C_GREY, lw=0.8)
        ax.legend(fontsize=8, frameon=False, loc="upper left")
    style(ax, "Top-trader long/short account ratio (Binance)", "ratio")
    ax = axes[3]
    if taker is not None:
        ax.plot(taker.index, taker.values, color=C_PRICE, lw=0.8, label="taker buy/sell volume ratio")
        ax.plot(taker.index, taker.rolling(30).mean(), color=C_ALT, lw=1.0, label="30d MA")
        ax.axhline(1.0, color=C_GREY, lw=0.8)
        ax.legend(fontsize=8, frameon=False, loc="upper left")
    # DVOL for SOL was discontinued by Deribit on 2022-11-25, so the volatility read here is
    # realized (30d log-return sigma, annualised) computed from the committed price series.
    rv = (np.log(px).diff().rolling(30).std() * np.sqrt(365) * 100).dropna()
    rv = rv.loc[rv.index >= pd.Timestamp("2021-12-01", tz="UTC")]
    ax2 = ax.twinx()
    ax2.plot(rv.index, rv.values, color=C_RED, lw=1.0, alpha=0.75, label="30d realized vol (ann.)")
    ax2.tick_params(labelsize=8)
    ax2.set_ylabel("realized vol %", fontsize=9, color=C_RED)
    ax2.legend(fontsize=8, frameon=False, loc="upper right")
    style(ax, "Taker buy/sell ratio and 30d realized volatility", "ratio")
    save(fig, out_dir, "06_sol_derivatives.png")

    # ------------------------------------------------------------ 07 macro backdrop
    dxy = load("dxy")
    m2 = load("fred_us_m2", col="value")
    stab_all = load("stablecoin_total_liquidity", col="total_cap_usd")
    fng = load("fear_greed", col="value")
    vix = load("vix")
    spx = load("sp500")

    start = px.index[0]
    fig, axes = plt.subplots(4, 1, figsize=(13, 11.5), sharex=True, constrained_layout=True)
    ax = axes[0]
    d = dxy.loc[start:]
    ax.plot(d.index, d.values, color=C_PRICE, lw=0.9, label="DXY")
    ax.plot(d.index, d.rolling(200).mean(), color=C_RED, lw=1.2, label="200d MA (firm = headwind)")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    style(ax, "Dollar index vs its 200d MA")
    ax = axes[1]
    m2v = (m2 / m2.shift(freq="365D") - 1).dropna() * 100
    m2v = m2v.loc[start:]
    ax.plot(m2v.index, m2v.values, color=C_GREEN, lw=1.2, label="US M2 YoY %")
    ax.axhline(4.0, color=C_GREY, ls=":", lw=0.8)
    ax.axhline(1.0, color=C_GREY, ls=":", lw=0.8)
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    style(ax, "US M2 year-over-year (%, monthly FRED)", "%")
    ax = axes[2]
    s = stab_all.loc[start:] / 1e9
    ax.plot(s.index, s.values, color=C_PRICE, lw=1.1, label="total stablecoin cap")
    ax.set_yscale("log")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    style(ax, "Total stablecoin supply, all chains (USD bn, log)", "USD bn")
    ax = axes[3]
    f = fng.loc[start:]
    ax.fill_between(f.index, f.values, 50, where=f.values >= 50, color=C_GREEN, alpha=0.3)
    ax.fill_between(f.index, f.values, 50, where=f.values < 50, color=C_RED, alpha=0.3)
    ax.plot(f.index, f.values, color="#333333", lw=0.7)
    ax.axhline(30, color=C_GREY, ls=":", lw=0.8)
    ax.axhline(70, color=C_GREY, ls=":", lw=0.8)
    ax.set_ylim(0, 100)
    style(ax, "Crypto Fear and Greed (contrarian trimmer, not a driver)")
    save(fig, out_dir, "07_macro_backdrop.png")

    # ------------------------------------------------------------ 08 liquidity map
    # Built in-process from the SAME module the CLI uses, so the chart cannot drift
    # from the printed shelf table (no second implementation, no JSON middleman).
    try:
        sys.path.insert(0, str(ROOT / "strategies"))
        import liquidity_map as lmap
        ldf = lmap.okx_candles(336, inst="SOL-USDT-SWAP")
        oi_usd, oi_src = lmap.open_interest("SOL")
        grid = lmap.build_grid(ldf, oi_usd, lmap.LEVERAGE_PROFILES["balanced"], 336)
        above, below = lmap.key_levels(grid)
        mat = np.array(grid["matrix"]) / 1e6            # USD m per price bin
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
        a1.set_title(f"Modelled liquidation heatmap, SOL perps  (OI {oi_usd/1e9:,.2f}B, {oi_src})",
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
        save(fig, out_dir, "08_sol_liquidation_map.png")
    except Exception as exc:
        print(f"  WARN liquidity map chart skipped: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------ 09 composite score history
    sys.path.insert(0, str(ROOT / "strategies"))
    import sol_macro_backtest as bt
    sig = bt.build_signals(px.index)
    score = bt.composite(sig, px.index)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 7.6), sharex=True,
                                 gridspec_kw={"height_ratios": [2, 1]}, constrained_layout=True)
    a1.plot(px.index, px.values, color=C_PRICE, lw=1.0)
    a1.set_yscale("log")
    a1.get_yaxis().set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:g}"))
    style(a1, "SOL price (log) against the regime score below")
    a2.fill_between(score.index, score.values, 0, where=score.values >= 0, color=C_GREEN, alpha=0.45)
    a2.fill_between(score.index, score.values, 0, where=score.values < 0, color=C_RED, alpha=0.45)
    a2.plot(score.index, score.values, color="#111111", lw=0.7)
    for lvl in (0.5, 1.5, -0.5, -1.5):
        a2.axhline(lvl, color=C_GREY, ls=":", lw=0.8)
    a2.set_ylim(-3, 3)
    style(a2, "Composite regime score (-3 .. +3): bands +1.5 hold/accumulate, -1.5 liquidate")
    save(fig, out_dir, "09_regime_score_history.png")

    # ------------------------------------------------------------ 10 volume
    fig, ax = plt.subplots(figsize=(13, 4.6), constrained_layout=True)
    v = vol.loc[start:]
    ax.bar(v.index, v.values / 1e9, width=1.0, color=C_FILL, alpha=0.5, label="daily USD volume (aggregate)")
    ax.plot(v.index, v.rolling(30).mean() / 1e9, color=C_PRICE, lw=1.2, label="30d MA")
    ax.set_yscale("log")
    style(ax, "SOL traded volume (USD bn/day, log) - participation, not direction", "USD bn")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    save(fig, out_dir, "10_sol_volume.png")

    print(f"\nDONE. charts in {out_dir}")


if __name__ == "__main__":
    main()
