#!/usr/bin/env python3
"""Backtest the macro regime signal against 2017-2026 BTC history."""
import requests, json, time
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

OUT = Path(__file__).parent.parent / "data" / "macro"
OUT.mkdir(parents=True, exist_ok=True)

def get_fng_history(limit=3000):
    """Full Fear & Greed history (daily since 2018)."""
    all_data = []
    r = requests.get(f"https://api.alternative.me/fng/?limit={limit}&format=json", timeout=30)
    data = r.json()["data"]
    return data  # [{value, value_classification, timestamp}]

def get_btc_price_history():
    """BTC daily prices from blockchain.info (keyless, back to 2010)."""
    r = requests.get("https://api.blockchain.info/charts/market-price?timespan=all&format=json", timeout=60)
    r.raise_for_status()
    data = r.json()
    seen = {}
    for pt in data["values"]:  # [{x: unix, y: price}]
        day = datetime.fromtimestamp(pt["x"], tz=timezone.utc).strftime("%Y-%m-%d")
        seen[day] = pt["y"]
    return seen

def main():
    print("Fetching Fear & Greed history...")
    fng = get_fng_history()
    print(f"  {len(fng)} FNG records")
    fng_by_day = {datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"): int(d["value"]) for d in fng}

    print("Fetching BTC price history (walking back ~9y)...")
    btc = get_btc_price_history()
    print(f"  {len(btc)} BTC daily prices")

    # Build daily series 2017-2026
    days = sorted(set(fng_by_day) | set(btc))
    days = [d for d in days if "2017-01-01" <= d <= "2026-08-02"]

    # Compute drawdown from rolling ATH and regime score each day
    ath = 0
    regime_days = []
    for d in days:
        if d in btc:
            ath = max(ath, btc[d])
            dd = (btc[d] / ath - 1) * 100
            f = fng_by_day.get(d, 50)
            score = 0
            score += 1 if f < 30 else (-1 if f > 70 else 0)
            score += 1 if dd < -40 else (-1 if dd > -10 else 0)
            regime_days.append({"date": d, "price": btc[d], "dd": dd, "fng": f, "score": score})

    # Find regime switches: when score crosses to <=-2 (sell) or >=+2 (buy)
    state = "HOLD"
    events = []
    for r in regime_days:
        new_state = "HOLD"
        if r["score"] <= -2: new_state = "CASH"
        elif r["score"] >= 2: new_state = "BUY"
        if new_state != state:
            events.append({**r, "from": state, "to": new_state})
            state = new_state

    print("\n=== REGIME SWITCHES 2017-2026 ===")
    for e in events:
        print(f"  {e['date']}: {e['from']:>4} -> {e['to']:>4}  (BTC ${e['price']:,.0f}, DD {e['dd']:.0f}%, F&G {e['fng']}, score {e['score']:+d})")

    # Key crash dates for sanity check
    print("\n=== SANITY CHECK vs known crashes ===")
    for crash, approx in [("2018 bear", "2018-01"), ("COVID 2020", "2020-03"), ("2022 bear", "2022-05"), ("2025 crash", "2025-01")]:
        hits = [e for e in events if e["to"] == "CASH" and e["date"].startswith(approx[:4])]
        near = [e for e in events if e["to"] == "CASH" and approx[5:7] and abs(int(e["date"][5:7]) - int(approx[5:7])) <= 3 and e["date"].startswith(approx[:4])]
        print(f"  {crash} ({approx}): CASH signals -> {[e['date'] for e in hits]}")

    # Save
    with open(OUT / "regime_backtest.json", "w") as f:
        json.dump({"events": events, "daily_count": len(regime_days)}, f, indent=2)
    print(f"\nSaved {len(events)} events -> {OUT/'regime_backtest.json'}")

if __name__ == "__main__":
    main()
