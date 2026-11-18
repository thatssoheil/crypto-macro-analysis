#!/usr/bin/env python3
"""
SOL MACRO REGIME BACKTEST (2020-04 -> today).

Honest pointwise backtest of the Solana regime models against buy & hold.
Every arm obeys the house backtest rules (AGENTS.md):

  - Position that earns day t's return is decided on day t-1's close (.shift(1)).
  - Daily closes only, $10k start, cash earns 0%, no costs (so results are an
    UPPER bound for any rule that trades: flips are printed to price the churn).
  - Calendar-anchored windows (no row offsets).
  - Growth series get the HIGH-is-good band function, level series the low-is-good
    one; the dollar vote is negated because a firm dollar is risk-off.

Arms:
  1. SOL buy & hold (the bar - same rule as strategies/hold_benchmark.py for BTC)
  2. 200d MA filter            (the BTC workhorse: guarded on BTC, unproven on SOL)
  3. 50d MA filter             (higher-beta asset, faster leg capture)
  4. 50d MA + DD-20% breaker
  5. Dual filter: SOL 200d AND SOL/BTC 200d (rotation gate)
  6. Composite >= +0.5
  7. Composite >= 0
  8. Composite CORE only (drops the two experimental Solana-native signals) >= 0
     -> this is the A/B: do stablecoin growth on Solana + DEX activity earn their
        place, or is the composite better without them?
  9. Composite CORE >= +0.5

Windows: FULL 2020-04-10 -> today, BEAR 2020-04-10 -> 2022-12-31,
         RECOVERY 2023-01-01 -> today.

Stateless: prints to stdout, saves nothing.
"""
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"
START = "2020-04-10"
END = None                              # None = last available close
BEAR_END, RECOV_START = "2022-12-31", "2023-01-01"


def load(name, date_col="date", col="close"):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[col] if col in df.columns else df


def slope(s, n=200):
    return np.sign(s - s.rolling(n).mean())


def bands_low_is_good(s, lo_v, hi_v):
    """+1 below lo_v, -1 above hi_v (IMPLIED VOL / SPREAD style series)."""
    out = pd.Series(0.0, index=s.index)
    out[s < lo_v] = 1.0
    out[s > hi_v] = -1.0
    return out


def bands_high_is_good(s, neg, pos):
    """+1 above pos, -1 below neg (GROWTH series: stablecoins, M2, Fed BS)."""
    out = pd.Series(0.0, index=s.index)
    out[s > pos] = 1.0
    out[s < neg] = -1.0
    return out


def pct_change_days(s, days):
    """Calendar-anchored percentage change (row offsets lie on sparse series)."""
    s = s.resample("D").ffill().dropna()
    return s / s.shift(days) - 1


def build_signals(idx):
    """Return {name: (series_on_idx, weight, experimental_flag)}."""
    sig = {}

    # A. LIQUIDITY (2.0)
    u10, u3m = load("us10y"), load("us3m")
    curve = (u10 - u3m.reindex(u10.index).ffill()).dropna()
    sig["curve"] = (pd.Series(np.where(curve > 0, 1.0, -1.0), index=curve.index), 2.0, False)

    stab = load("stablecoin_total_liquidity", col="total_cap_usd")
    if stab is not None:
        sig["stablecoin"] = (bands_high_is_good(pct_change_days(stab, 30), -0.02, 0.02), 2.0, False)

    sig["dxy"] = (-slope(load("dxy")), 1.5, False)          # firm dollar = risk-off

    m2 = load("fred_us_m2", col="value")
    if m2 is not None:
        yoy = m2 / m2.shift(freq="365D") - 1
        sig["m2"] = (bands_high_is_good(yoy, 0.01, 0.04), 2.0, False)

    fbs = load("fred_fed_balance_sheet", col="value")
    if fbs is not None:
        fbs_d = fbs.resample("D").ffill()
        sig["fed_bs"] = (bands_high_is_good((fbs_d / fbs_d.shift(60) - 1).reindex(fbs.index),
                                            -0.01, 0.01), 1.5, False)

    # B. RISK APPETITE (1.5)
    sig["vix"] = (bands_low_is_good(load("vix"), 20.0, 30.0), 1.5, False)
    sig["spx"] = (slope(load("sp500")), 1.5, False)
    hy = load("fred_hy_spread", col="value")
    if hy is not None:
        sig["credit"] = (bands_low_is_good(hy, 3.5, 5.5), 1.5, False)

    # C. SOL INTERNALS
    sol = load("solusd_daily_yahoo", "ts")
    sig["sol_ma"] = (slope(sol), 2.0, False)

    btc = load("btcusd_daily_bitstamp", "ts")
    solbtc = (sol / btc.reindex(sol.index, method="ffill")).dropna()
    sig["solbtc_ma"] = (slope(solbtc), 1.5, False)

    tvl = load("sol_tvl_defillama", col="tvl_usd")
    if tvl is not None:
        tvl_d = tvl.resample("D").ffill().dropna()
        sig["sol_tvl"] = (slope(tvl_d, 60), 1.0, False)

    sstab = load("sol_stablecoins_defillama", col="usd")
    if sstab is not None:
        sig["sol_stable"] = (bands_high_is_good(pct_change_days(sstab, 30), -0.02, 0.02), 1.0, True)

    dex = load("sol_dex_volume_defillama", col="usd")
    if dex is not None:
        dex = dex.resample("D").ffill().dropna()
        ratio = dex.rolling(7).median() / dex.rolling(90).median()
        sig["sol_dex"] = (bands_high_is_good(ratio, 0.75, 1.25), 0.5, True)

    fng = load("fear_greed", col="value")
    if fng is not None:
        sig["fng"] = (bands_low_is_good(fng, 30.0, 70.0), 0.5, False)

    # D. INFLATION / REAL (1.0)
    ry = load("fred_real_yield10y", col="value")
    if ry is not None:
        sig["real_yield"] = (bands_low_is_good(ry, 1.5, 2.5), 1.0, False)
    cpi = load("fred_cpi", col="value")
    if cpi is not None:
        sig["cpi"] = (bands_low_is_good(cpi / cpi.shift(freq="365D") - 1, 0.03, 0.05), 0.5, False)
    sig["gold"] = (slope(load("gold")), 0.5, False)

    return {k: (s.reindex(idx).ffill() if isinstance(s, pd.Series) else s, w, x)
            for k, (s, w, x) in sig.items()}


def composite(sig, idx, drop_experimental=False):
    use = {k: v for k, v in sig.items() if not (drop_experimental and v[2])}
    wts = pd.Series({k: v[1] for k, v in use.items()})
    # reindex to THIS window's index - otherwise the score carries the full index and
    # multiplying it into a window's returns silently makes the whole arm NaN.
    df = pd.DataFrame({k: v[0].reindex(idx) for k, v in use.items()})
    wsum = (df.notna() * wts).sum(axis=1)
    return (df.fillna(0) * wts).sum(axis=1) / wsum * 3


def stats(eq, rets, in_market, name):
    dd = (eq / eq.cummax() - 1).min() * 100
    years = len(eq) / 365.25
    return {
        "name": name,
        "final": float(eq.iloc[-1]),
        "pct": float((eq.iloc[-1] / 10000 - 1) * 100),
        "cagr": float(((eq.iloc[-1] / 10000) ** (1 / years) - 1) * 100) if years > 0 else 0.0,
        "max_dd": float(dd),
        "cash_days": int((in_market == 0).sum()),
        "flips": int((in_market.diff().abs() > 0).sum()),
    }


def run_window(px, sig, label, lo, hi):
    """Simulate every arm over px.loc[lo:hi]. Returns (results list, equity dict)."""
    lo, hi = pd.Timestamp(lo, tz="UTC"), pd.Timestamp(hi, tz="UTC")
    p = px.loc[lo:hi]
    if len(p) < 60:
        return [], {}
    idx = p.index
    rets = p.pct_change().fillna(0)
    sc_all = composite(sig, idx)
    sc_core = composite(sig, idx, drop_experimental=True)

    ma200, ma50 = p.rolling(200).mean(), p.rolling(50).mean()
    solbtc_s = sig["solbtc_ma"][0].loc[lo:hi]
    dd_pct = (p / p.cummax() - 1) * 100

    arms = {
        "SOL buy & hold": pd.Series(1.0, index=idx),
        "200d MA filter": (p >= ma200).astype(float),
        "50d MA filter": (p >= ma50).astype(float),
        "50d MA + DD-20% breaker": ((p >= ma50) & (dd_pct >= -20)).astype(float),
        "Dual: SOL 200d AND SOL/BTC 200d": ((p >= ma200) & (slope(solbtc_s) > 0)).astype(float),
        "Composite >= +0.5 (all signals)": (sc_all >= 0.5).astype(float),
        "Composite >= 0 (all signals)": (sc_all >= 0).astype(float),
        "Composite >= 0 CORE (no SOL-native extras)": (sc_core >= 0).astype(float),
        "Composite >= +0.5 CORE": (sc_core >= 0.5).astype(float),
    }

    rows, eqs = [], {}
    for name, in_market_raw in arms.items():
        if name == "SOL buy & hold":
            inm = pd.Series(1.0, index=idx)          # the bar: no decision to lag
        else:
            inm = in_market_raw.shift(1).fillna(0.0)  # t-1 decision earns day t
        eq = (1 + rets * inm).cumprod() * 10000
        r = stats(eq, rets, inm, name)
        r["window"] = label
        rows.append(r)
        eqs[name] = eq
    return rows, eqs


def show(rows, label):
    print(f"\n--- {label} ---")
    print(f"{'Strategy':44} {'Final ($)':>13} {'Return %':>11} {'CAGR %':>9} {'Max DD %':>9} {'Cash d':>7} {'Flips':>6}")
    print("-" * 106)
    for r in rows:
        print(f"{r['name']:44} ${r['final']:>12,.0f} {r['pct']:>+10,.1f}% {r['cagr']:>+8.1f}% "
              f"{r['max_dd']:>8.1f}% {r['cash_days']:>7} {r['flips']:>6}")
    bh = next((r for r in rows if r["name"] == "SOL buy & hold"), None)
    if bh and bh["final"] > 0:
        print("\n  multiples vs buy & hold: " + " | ".join(
            f"{r['name'].split(' (')[0][:28]} {r['final']/bh['final']:.2f}x" for r in rows[1:]))


def main():
    px = load("solusd_daily_yahoo", "ts")
    if px is None:
        raise SystemExit("solusd_daily_yahoo.csv missing - run build_macro_dataset.py --solana-only")
    px = px[~px.index.duplicated(keep="last")].sort_index()
    px = px.loc[START:END] if END else px.loc[START:]
    idx = px.index
    sig = build_signals(idx)

    print("=" * 106)
    print(f"SOL MACRO REGIME BACKTEST  {idx[0].date()} -> {idx[-1].date()}  "
          f"({len(idx)} daily closes, true closes, t-1 decision, cash 0%, no costs)")
    print(f"data: solusd_daily_yahoo (longest keyless series: SOL spot opened 2020-04-10)")
    print("=" * 106)

    full, eqs = run_window(px, sig, "FULL", str(idx[0].date()), str(idx[-1].date()))
    show(full, f"FULL {idx[0].date()} -> {idx[-1].date()}")

    bear, _ = run_window(px, sig, "BEAR", str(idx[0].date()), BEAR_END)
    show(bear, f"BEAR {idx[0].date()} -> {BEAR_END}")

    rec, _ = run_window(px, sig, "RECOVERY", RECOV_START, str(idx[-1].date()))
    show(rec, f"RECOVERY {RECOV_START} -> {idx[-1].date()}")

    # Yearly shape of the two arms that matter for the decision.
    print("\n--- Yearly returns %, FULL window ---")
    tracked = ["SOL buy & hold", "200d MA filter", "50d MA filter",
               "Composite >= 0 (all signals)", "Composite >= 0 CORE (no SOL-native extras)"]
    yearly = {}
    for label in tracked:
        e = eqs[label]
        y = e.resample("YE").last()
        y = y.pct_change()
        y.iloc[0] = e.resample("YE").last().iloc[0] / 10000 - 1
        yearly[label] = {str(d.year): round(float(v) * 100, 1) for d, v in y.items()}
    yrs = sorted({y for d in yearly.values() for y in d})
    head = f"{'Year':6}" + "".join(f"{t[:18]:>20}" for t in tracked)
    print(head)
    print("-" * len(head))
    for y in yrs:
        print(f"{y:6}" + "".join(f"{yearly[t].get(y, float('nan')):>20.1f}" for t in tracked))

    # A/B verdict on the experimental Solana-native signals.
    print("\n--- A/B: do the SOL-native signals (stablecoin growth + DEX activity) earn their weight? ---")
    for rows, label in ((full, "FULL"), (bear, "BEAR"), (rec, "RECOVERY")):
        a = next(r for r in rows if r["name"] == "Composite >= 0 (all signals)")
        b = next(r for r in rows if r["name"] == "Composite >= 0 CORE (no SOL-native extras)")
        bh = next(r for r in rows if r["name"] == "SOL buy & hold")
        print(f"  {label:9} with ${a['final']:>12,.0f} (DD {a['max_dd']:>6.1f}%, {a['flips']} flips)  "
              f"without ${b['final']:>12,.0f} (DD {b['max_dd']:>6.1f}%, {b['flips']} flips)  "
              f"hold ${bh['final']:>12,.0f}   ->  {'ADD' if a['final'] > b['final'] else 'NO ADD'} "
              f"({a['final']/b['final']:.2f}x on the with/without arm)")
    print("\nRead this as structure, not as a return forecast: one asset, one 6.5-year window,")
    print("no costs, and a 2022 that dominates every number (-96% peak to trough).")
    print("A rule that only looks good because it sat out 2022 is a one-episode result.")


if __name__ == "__main__":
    main()
