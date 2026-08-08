#!/usr/bin/env python3
"""
MACRO REGIME ENGINE - 6-month cadence crypto allocation switch.
Decides: HOLD crypto / LIQUIDATE to cash / ACCUMULATE on drawdown.

Layer 1: Regime score from macro + market indicators (each +1 risk-on / -1 risk-off)
Layer 2: Entry trigger (only when Risk-ON): buy deep drawdowns

Data sources (all keyless, free):
  - Fear & Greed: api.alternative.me/fng/
  - BTC dominance + BTC price: api.coingecko.com/api/v3/global + /coins/bitcoin
  - DXY: no free keyless source -> optional FRED key (stlouisfed) slots in here

Output: verdict to stdout (stateless - nothing persisted)
"""
import sys, os, csv
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests



# FRED key from env or config (optional - enriches with M2/DXY/rates when present)
FRED_KEY = os.environ.get("FRED_API_KEY", "")

def get_fng():
    """Fear & Greed index (0-100). <30 fear (buy), >70 greed (sell)."""
    r = requests.get("https://api.alternative.me/fng/?limit=2", timeout=15)
    data = r.json()["data"]
    now = int(data[0]["value"])
    prev = int(data[1]["value"])
    return now, now - prev

def get_coingecko():
    """BTC dominance + BTC price from CoinGecko global endpoint."""
    g = requests.get("https://api.coingecko.com/api/v3/global", timeout=15).json()["data"]
    btc_d = g["market_cap_percentage"]["btc"]
    # BTC price via /coins/bitcoin (simpler than global which lacks price)
    b = requests.get("https://api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&community_data=false&developer_data=false", timeout=15).json()
    price = b["market_data"]["current_price"]["usd"]
    ath = b["market_data"]["ath"]["usd"]
    return btc_d, price, ath

def get_fred(series):
    """FRED series via api.stlouisfed.org (needs FRED_API_KEY env)."""
    if not FRED_KEY:
        return None
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series}&api_key={FRED_KEY}&file_type=json&sort_order=desc&limit=2"
    r = requests.get(url, timeout=15).json()
    vals = [float(o["value"]) for o in r["observations"] if o["value"] != "."]
    if len(vals) >= 2:
        return vals[0], (vals[0] / vals[1] - 1) * 100  # latest, YoY/period change %
    return None

def regime_score(fng, btc_d, btc_price, ath, fred_data):
    """Composite regime score: +1 risk-on, -1 risk-off per indicator."""
    score = 0
    reasons = []

    # 1. Fear & Greed: extreme fear = contrarian risk-on (buy), greed = risk-off (sell)
    if fng < 30:
        score += 1; reasons.append(f"Fear & Greed {fng} (<30): contrarian RISK-ON (buy fear)")
    elif fng > 70:
        score -= 1; reasons.append(f"Fear & Greed {fng} (>70): RISK-OFF (crowded, take profit)")
    else:
        reasons.append(f"Fear & Greed {fng}: neutral")

    # 2. BTC drawdown from ATH: deep = risk-on accumulation, shallow/ATH = mature
    dd = (btc_price / ath - 1) * 100
    if dd < -40:
        score += 1; reasons.append(f"BTC drawdown {dd:.0f}% from ATH (<-40%): RISK-ON (accumulate)")
    elif dd > -10:
        score -= 1; reasons.append(f"BTC near ATH (drawdown {dd:.0f}%): RISK-OFF (late cycle)")
    else:
        reasons.append(f"BTC drawdown {dd:.0f}% from ATH: neutral")

    # 3. BTC dominance: rising = flight to safety (risk-off for alts), falling = altseason (risk-on)
    #    (trend proxy: use absolute level as coarse signal)
    if btc_d < 45:
        score += 1; reasons.append(f"BTC.D {btc_d:.1f}% (<45%): altseason RISK-ON")
    elif btc_d > 60:
        score -= 1; reasons.append(f"BTC.D {btc_d:.1f}% (>60%): flight to BTC RISK-OFF for alts")
    else:
        reasons.append(f"BTC.D {btc_d:.1f}%: neutral")

    # 4. FRED M2 YoY (if key present): liquidity expansion = risk-on
    if fred_data and "m2" in fred_data:
        m2 = fred_data["m2"]
        if m2[1] > 3:
            score += 1; reasons.append(f"M2 YoY {m2[1]:+.1f}% (>+3%): liquidity RISK-ON")
        elif m2[1] < -1:
            score -= 1; reasons.append(f"M2 YoY {m2[1]:+.1f}% (<-1%): contraction RISK-OFF")
        else:
            reasons.append(f"M2 YoY {m2[1]:+.1f}%: neutral")

    return score, reasons

def verdict(score):
    if score >= 3:  return "HOLD / ACCUMULATE", "Risk-ON. Hold crypto. Deploy cash on deep drawdowns (Layer 2)."
    if score >= 1:  return "HOLD", "Mildly risk-on. Hold existing positions, no new buys."
    if score <= -2: return "LIQUIDATE TO CASH", "Risk-OFF. Reduce/exit crypto, hold cash for better entry."
    return "NEUTRAL / REDUCE", "Mixed signals. Hold cash or reduce, wait for clearer regime."

def main():
    print("=== MACRO REGIME ENGINE ===")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    try:
        fng, fng_delta = get_fng()
        print(f"Fear & Greed: {fng} (delta {fng_delta:+d})")
    except Exception as e:
        print(f"FNG fetch failed: {e}"); return

    try:
        btc_d, btc_price, btc_ath = get_coingecko()
        print(f"BTC.D: {btc_d:.1f}%  BTC: ${btc_price:,.0f}  ATH: ${btc_ath:,.0f}")
    except Exception as e:
        print(f"CoinGecko fetch failed: {e}"); return

    fred_data = {}
    if FRED_KEY:
        for series, name in [("M2SL", "m2")]:
            try:
                v = get_fred(series)
                if v: fred_data[name] = v; print(f"FRED {series}: {v}")
            except Exception as e:
                print(f"FRED {series} failed: {e}")
    else:
        print("FRED key not set (optional) - skipping M2. Set FRED_API_KEY for full signal.")

    score, reasons = regime_score(fng, btc_d, btc_price, btc_ath, fred_data)
    v, desc = verdict(score)

    print(f"\n=== REGIME SCORE: {score:+d} -> {v} ===")
    for r in reasons: print(f"  - {r}")
    print(f"  Action: {desc}")

    # Layer 2: entry trigger (only meaningful in Risk-ON)
    dd = (btc_price / btc_ath - 1) * 100
    layer2 = "WAIT" 
    if score >= 1 and dd < -40 and fng < 30:
        layer2 = "DEPLOY CASH - deep drawdown + fear: buy tranche"
    elif score >= 1:
        layer2 = "HOLD - regime ok but no extreme entry signal (wait for -40% DD or F&G<30)"

    print(f"  Layer 2 (entry): {layer2}")

    # Stateless: print report to stdout, persist nothing.
    print(f"\n# Macro Regime Report - {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    print(f"## Verdict: **{v}** (score {score:+d})")
    print(f"**Action:** {desc}")
    print(f"**Layer 2 (entry):** {layer2}")
    print("| Indicator | Value | Signal |")
    print("|---|---|---|")
    print(f"| Fear & Greed | {fng} | {'buy fear' if fng<30 else 'sell greed' if fng>70 else 'neutral'} |")
    print(f"| BTC dominance | {btc_d:.1f}% | {'altseason' if btc_d<45 else 'flight to BTC' if btc_d>60 else 'neutral'} |")
    print(f"| BTC drawdown from ATH | {dd:.0f}% | {'accumulate' if dd<-40 else 'late cycle' if dd>-10 else 'neutral'} |")
    if fred_data and "m2" in fred_data:
        print(f"| M2 YoY | {fred_data['m2'][1]:+.1f}% | {'expansion' if fred_data['m2'][1]>3 else 'contraction' if fred_data['m2'][1]<-1 else 'neutral'} |")
    print(f"_Reported: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_")

if __name__ == "__main__":
    main()
