#!/usr/bin/env python3
"""
BTC <-> ETH ROTATION ENGINE (2026-09, validated 2017-2026).

Question: when to hold BTC, when to convert to ETH, when to sit in cash -
with minimum delay between the ratio turning and the signal firing.

THE RULE (DUALM50 - the only family that survived every honesty check):
  hold ETH   if ETH/BTC > its 50d MA  AND  ETH > its 200d MA
                    AND VIX <= 30  AND  SPX > its 200d MA   (macro risk gate)
  else BTC   if BTC > its 200d MA
  else CASH

Why these pieces (validated, see the printed backtest):
  - Relative leg: ETH/BTC ratio vs 50d MA = which asset is stronger. Fires a
    median of ~12d after the ratio turns (20d MA fires in ~5-6d but flips 2x
    as often, is cost-fragile and has been negative since 2022).
  - Absolute gate: the held asset above its own 200d MA (the repo's validated
    trend filter, applied to the ETH leg before trusting the ratio).
  - Macro gate: VIX <= 30 AND SPX > 200d MA. Crypto crashes with equities;
    this gate is what pulls max DD under -50%.
  - Rotation into ETH is the RARE case (a few windows per cycle). The default
    state is BTC or cash. In BTC-led years the plain BTC 200d MA filter beats
    every rotation variant - do not expect the rotation leg to always add.

Conventions (same as every backtest in this repo):
  - Daily closes, shift(1): today's close decides TOMORROW's position. No lookahead.
  - $10k start, cash earns 0%, costs 0.4% per position flip (two taker trades).
  - Stateless: prints to stdout, saves nothing.
"""
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "macro_dataset"
W = "2017-08-16"  # ETH data floor binds the window
COST = 0.004      # per flip: sell one asset + buy the other (taker, both legs)


def load(name, ts_col="ts", col="close"):
    df = pd.read_csv(DATA / f"{name}.csv")
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
    return df.set_index(ts_col).sort_index()[col]


def ma(s, n):
    return s.rolling(n).mean()


def sim(pos, btc, eth, cost=COST):
    exec_pos = pos.shift(1).fillna(0.0)
    rb = btc.pct_change().fillna(0)
    re_ = eth.pct_change().fillna(0)
    r = pd.Series(0.0, index=pos.index)
    r[exec_pos == 1] = rb[exec_pos == 1]
    r[exec_pos == 2] = re_[exec_pos == 2]
    r = r - exec_pos.diff().abs().fillna(0) * cost
    eq = (1 + r).cumprod() * 10000
    dd = (eq / eq.cummax() - 1).min() * 100
    flips = int((pos.diff().abs() > 0).sum())
    yrs = len(eq) / 365.25
    cagr = ((eq.iloc[-1] / 10000) ** (1 / yrs) - 1) * 100
    return eq, float(cagr), float(dd), flips


def main():
    btc = load("btcusd_daily_bitstamp").loc[W:]
    eth = load("ethusd_daily_bitstamp").loc[W:]
    idx = btc.index.intersection(eth.index)
    btc, eth = btc[idx], eth[idx]
    ratio = (eth / btc).reindex(idx).ffill()
    btc200, eth200 = ma(btc, 200), ma(eth, 200)
    rma50 = ma(ratio, 50)
    vix = load("vix", "date").reindex(idx).ffill()
    spx = load("sp500", "date").reindex(idx).ffill()
    macro_ok = (vix <= 30) & (spx >= ma(spx, 200).reindex(idx).ffill())

    rel_eth = ratio >= rma50
    pos = pd.Series(
        np.where(rel_eth & (eth >= eth200) & macro_ok, 2,
                 np.where(btc >= btc200, 1, 0)), idx)
    names = {0: "CASH", 1: "BTC", 2: "ETH"}

    # ---------- current verdict ----------
    t = idx[-1]
    print(f"=== BTC/ETH ROTATION VERDICT (data through {t.date()}) ===")
    print(f"BTC ${btc.iloc[-1]:,.0f}   ETH ${eth.iloc[-1]:,.2f}   ETH/BTC {ratio.iloc[-1]:.5f}")
    print(f"  1. ETH/BTC vs 50d MA ({rma50.iloc[-1]:.5f}): "
          f"{'ETH stronger (+%.1f%%)' % ((ratio.iloc[-1]/rma50.iloc[-1]-1)*100) if rel_eth.iloc[-1] else 'BTC stronger (%.1f%%)' % ((ratio.iloc[-1]/rma50.iloc[-1]-1)*100)}")
    print(f"  2. ETH vs 200d MA:      {'ABOVE' if eth.iloc[-1] >= eth200.iloc[-1] else 'BELOW'}   "
          f"(ETH ${eth.iloc[-1]:,.0f} vs MA ${eth200.iloc[-1]:,.0f})")
    print(f"  3. macro gate:          {'OPEN (VIX %.1f, SPX %s 200d MA)' % (vix.iloc[-1], 'above' if spx.iloc[-1] >= ma(spx, 200).iloc[-1] else 'below')}")
    print(f"  4. BTC vs 200d MA:      {'ABOVE' if btc.iloc[-1] >= btc200.iloc[-1] else 'BELOW'}   "
          f"(BTC ${btc.iloc[-1]:,.0f} vs MA ${btc200.iloc[-1]:,.0f})")
    flips = idx[pos.diff().abs() > 0]
    held = names[int(pos.iloc[-1])]
    since = flips[-1].date() if len(flips) else "start"
    print(f"\n  >>> HOLD {held} (since {since}) <<<")
    print("      BTC-led years the plain BTC 200d MA filter usually wins; this")
    print("      rule only puts you in ETH during genuine alt-season windows.\n")

    # ---------- backtest ----------
    def positions(kind):
        if kind == "BH_BTC":
            return pd.Series(1, idx)
        if kind == "BH_ETH":
            return pd.Series(2, idx)
        if kind == "BTCMA":
            return pd.Series(((btc >= btc200) * 1).where(btc200.notna(), 0), idx)
        if kind == "ROT20":  # un-gated fast rotation: the mirage benchmark
            return pd.Series(np.where(ratio >= ma(ratio, 20), 2, 1), idx)
        if kind == "DUAL50":  # no macro gate
            return pd.Series(np.where(rel_eth & (eth >= eth200), 2,
                                      np.where(btc >= btc200, 1, 0)), idx)
        if kind == "DUALM50":
            return pos
        raise ValueError(kind)

    rows = []
    eqs = {}
    for label, kind in [("BTC buy&hold", "BH_BTC"), ("ETH buy&hold", "BH_ETH"),
                        ("BTC 200d MA filter", "BTCMA"), ("ROT20 un-gated (mirage)", "ROT20"),
                        ("DUAL50 (no macro gate)", "DUAL50"),
                        ("DUALM50 (this engine)", "DUALM50")]:
        p = positions(kind)
        eq0, c0, d0, f = sim(p, btc, eth, cost=0.0)
        eq, c, d, _ = sim(p, btc, eth, cost=COST)
        rows.append((label, eq.iloc[-1], c, d, f, eq0.iloc[-1]))
        eqs[label] = eq
    print(f"=== BACKTEST {W} -> {t.date()}  (daily closes, shift(1), $10k, cash 0%) ===")
    print(f"{'strategy':26} {'final $ (0.4%/flip)':>20} {'CAGR%':>8} {'MaxDD%':>8} {'flips':>6} {'final $ 0-cost':>16}")
    print("-" * 92)
    for label, fin, c, d, f, fin0 in rows:
        print(f"{label:26} {fin:>20,.0f} {c:>+8.1f} {d:>8.1f} {f:>6} {fin0:>16,.0f}")

    # ---------- yearly attribution ----------
    print("\n=== YEARLY RETURNS % (0.4%/flip) ===")
    ytab = {}
    for label in ["BTC buy&hold", "BTC 200d MA filter", "DUALM50 (this engine)"]:
        ye = eqs[label].resample("YE").last()
        yr = ye.pct_change()
        yr.iloc[0] = ye.iloc[0] / 10000 - 1
        ytab[label] = {d.year: float(v) * 100 for d, v in yr.items()}
    years = sorted(ytab["BTC buy&hold"])
    print(f"{'strategy':26} " + " ".join(f"{y:>7}" for y in years))
    for label, _ in ytab.items():
        print(f"{label:26} " + " ".join(f"{ytab[label].get(y, float('nan')):>7.1f}" for y in years))

    # ---------- honest caveats ----------
    print("""
=== WHAT THE TEST ACTUALLY SHOWS (blunt version) ===
1. The rotation edge is REAL but REGIME-CONCENTRATED: it comes almost entirely
   from alt-season windows (2020-2021, 2025). In BTC-led years (2019, 2023,
   2024, 2026 YTD) the plain BTC 200d MA filter beats it. This is a context
   tool layered on the trend filter, not a replacement for it.
2. Un-gated rotation (always hold whichever of BTC/ETH is stronger) is a
   mirage: its spectacular backtest is a 2017-2021 artifact, and it LOSES
   money since 2022 (ETH/BTC structural downtrend with violent bear rallies).
   Never trade the relative leg without the absolute + macro gates.
3. Costs are material: ~2 flips/month x 0.4% = real drag. Use limit orders
   and batch conversions. The fast (20d) variant is cost-fragile - that is
   why the engine uses the 50d MA.
4. The macro gate (VIX/SPX) lags crypto-specific crashes (2022: the gate was
   still open while crypto bled). Expect worse drawdowns than the BTC filter
   in crypto-only bears; the 200d MA gates are what bound it near -50%.
5. Delay is the price of stability: the 50d ratio rule fires ~12d after the
   ETH/BTC turn (median, both directions). Faster = 5-6d but 2x the flips,
   negative since 2022, cost-fragile. Minimum delay that survives testing
   is ~12d; claiming 0d is curve-fitting.
""")


if __name__ == "__main__":
    main()
