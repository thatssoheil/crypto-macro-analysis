#!/usr/bin/env python3
"""Macro regime v2 - trend-aware. Backtest window: 2018-05 -> present.
NOTE: the F&G join binds the start (F&G only exists 2018-05-17+), so despite
the old "2017-2026" label this backtest's window actually begins 2018-05 -
that is why its results differ from macro_backtest_v4.py (which starts
2017-01-01 on the local Bitstamp dataset). Kept for lineage; for the clean
2017-2026 / 2011-2026 200d-MA numbers use macro_backtest_deep.py.
Fix: CASH when price < 200d MA (real bear regime) OR (deep drawdown + rising), not mere greed.
BUY when drawdown from ATH > -40% AND F&G < 30 (capitulation).
"""
import requests
from datetime import datetime, timezone
from pathlib import Path
import numpy as np



def get_fng_history(limit=3000):
    r = requests.get(f"https://api.alternative.me/fng/?limit={limit}&format=json", timeout=30)
    data = r.json()["data"]
    return {datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"): int(d["value"]) for d in data}

def get_btc():
    """BTC daily prices from blockchain.info (keyless, back to 2009).
    IMPORTANT: sampled=false gives true daily; default is weekly (4d gaps)."""
    r = requests.get("https://api.blockchain.info/charts/market-price?timespan=all&format=json&sampled=false", timeout=60)
    r.raise_for_status()
    return {datetime.fromtimestamp(pt["x"], tz=timezone.utc).strftime("%Y-%m-%d"): pt["y"] for pt in r.json()["values"]}

def main():
    print("Fetching data...")
    fng = get_fng_history()
    btc = get_btc()
    print(f"  FNG: {len(fng)} days, BTC: {len(btc)} days")

    days = sorted(d for d in (set(fng) & set(btc)) if "2017-01-01" <= d <= "2026-08-02")
    print(f"  overlap days: {len(days)}")

    # Build price series with 200d MA
    prices = np.array([btc[d] for d in days])
    ma200 = np.full(len(prices), np.nan)
    for i in range(199, len(prices)):
        ma200[i] = prices[i-199:i+1].mean()

    ath = 0
    state = "HOLD"
    events = []
    for i, d in enumerate(days):
        p = prices[i]
        ath = max(ath, p)
        dd = (p / ath - 1) * 100
        f = fng.get(d, 50)
        below_ma = (not np.isnan(ma200[i])) and p < ma200[i]

        # v2 signal: CASH on trend break (price < 200d MA), BUY on capitulation
        new_state = "HOLD"
        if below_ma:
            new_state = "CASH"
        elif dd < -40 and f < 30:
            new_state = "BUY"
        if new_state != state:
            events.append({"date": d, "price": round(p), "dd": round(dd), "fng": f,
                           "ma200": round(ma200[i]) if not np.isnan(ma200[i]) else None,
                           "below_ma": bool(below_ma), "from": state, "to": new_state})
            state = new_state

    print(f"\n=== REGIME v2 SWITCHES (trend-aware) ===")
    for e in events:
        print(f"  {e['date']}: {e['from']:>4} -> {e['to']:>4}  (BTC ${e['price']:,}, DD {e['dd']:.0f}%, F&G {e['fng']}, <200MA: {e['below_ma']})")

    # Simulate: hold BTC, or cash on CASH signal, rebuy on BUY
    print("\n=== SIMULATION: trend-follow (cash when <200MA) vs buy-hold ===")
    # trend-follow: in market when price >= 200MA (re-enter on reclaim)
    in_market = [True]  # start holding
    for i in range(1, len(days)):
        cur = in_market[-1]
        if not np.isnan(ma200[i]):
            if prices[i] < ma200[i]:
                cur = False
            elif prices[i] > ma200[i]:
                cur = True
        in_market.append(cur)
    # note: daily re-eval, no lag on signal

    # compute both equity curves (start $10k, 2017)
    eq_tf = [10000.0]; eq_bh = [10000.0]
    for i in range(1, len(days)):
        ret = prices[i] / prices[i-1] - 1
        eq_bh.append(eq_bh[-1] * (1 + ret))
        eq_tf.append(eq_tf[-1] * (1 + ret if in_market[i] else 1.0))  # cash: hold value, 0% yield
    # cash earns 0 (conservative, no yield)

    # stats
    import pandas as pd
    idx = pd.to_datetime(days)
    bh = pd.Series(eq_bh, index=idx)
    tf = pd.Series(eq_tf, index=idx)
    print(f"  Buy-hold: ${bh.iloc[-1]:,.0f} ({bh.iloc[-1]/10000*100-100:+.0f}%)")
    print(f"  Trend-follow: ${tf.iloc[-1]:,.0f} ({tf.iloc[-1]/10000*100-100:+.0f}%)")
    print(f"  Max DD buy-hold: {(bh/bh.cummax()-1).min()*100:.0f}%")
    print(f"  Max DD trend-follow: {(tf/tf.cummax()-1).min()*100:.0f}%")

    # yearly
    print("\n  Yearly returns:")
    bh_y = bh.resample('YE').last().pct_change().fillna(bh.iloc[0]/10000-1) * 100
    tf_y = tf.resample('YE').last().pct_change().fillna(tf.iloc[0]/10000-1) * 100
    for yr in bh_y.index:
        print(f"    {yr.year}: BH {bh_y[yr]:+6.1f}%  TF {tf_y[yr]:+6.1f}%")

    # Stateless: results print above; nothing persisted.
    print(f"\nSaved -> (stateless: results printed above, nothing written)")

if __name__ == "__main__":
    main()
