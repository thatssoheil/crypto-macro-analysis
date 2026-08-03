#!/usr/bin/env python3
"""
BTC MASTER DATASET BUILDER - fetch all correlated charts into data/macro_dataset/
Sources verified keyless & reachable 2026-08-03. FRED (M2/DFF) stubbed for later key.
Each chart -> data/macro_dataset/<name>.csv + manifest.json entry.
"""
import requests, json, time, csv, sys
from datetime import datetime, timezone, date
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).parent.parent / "data" / "macro_dataset"
OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) dataset-builder"}
manifest = {"built": datetime.now(timezone.utc).isoformat(), "charts": {}}

def save_csv(name, rows, header):
    """rows: list of lists; header: list of str"""
    path = OUT / f"{name}.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    manifest["charts"][name] = {"file": path.name, "rows": len(rows),
                                "source": "", "span": f"{rows[0][0]} -> {rows[-1][0]}" if rows else ""}
    print(f"  saved {name}.csv ({len(rows)} rows)")

def get(url, tries=4, base_wait=5):
    for i in range(tries):
        try:
            r = requests.get(url, timeout=40, headers=UA)
            if r.status_code == 200: return r
            if r.status_code == 429:
                w = base_wait * (i + 1) * 2
                print(f"    429, waiting {w}s..."); time.sleep(w); continue
            print(f"    HTTP {r.status_code}"); return None
        except Exception as e:
            print(f"    err {type(e).__name__}, retry"); time.sleep(base_wait)
    return None

# ---------- 1. Bitstamp BTCUSD daily (2011+) ----------
print("== Bitstamp BTCUSD daily ==")
rows = []
step = 86400
# Bitstamp ohlc returns up to 1000 candles; walk back with `step`-sized windows via `start` param
start = int(datetime.now(timezone.utc).timestamp())
while True:
    url = f"https://www.bitstamp.net/api/v2/ohlc/btcusd/?step={step}&limit=1000&start={start}"
    r = get(url)
    if not r: break
    ohlc = r.json()["data"]["ohlc"]
    if not ohlc: break
    for o in ohlc:
        rows.append([datetime.fromtimestamp(int(o["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"),
                     o["open"], o["high"], o["low"], o["close"], o["volume"]])
    oldest = int(ohlc[0]["timestamp"])
    if len(ohlc) < 1000: break
    start = oldest - step
    print(f"  ...{rows[-1][0]} ({len(rows)} rows)")
    time.sleep(0.6)
rows = sorted(set(tuple(r) for r in rows))  # dedupe
save_csv("btcusd_daily_bitstamp", sorted(rows), ["date","open","high","low","close","volume"])
manifest["charts"]["btcusd_daily_bitstamp"]["source"] = "Bitstamp API v2 ohlc step=86400"

# ---------- 2. blockchain.info on-chain (2009+) ----------
print("== blockchain.info on-chain ==")
for chart in ["hash-rate", "difficulty", "n-unique-addresses", "n-transactions", "market-cap", "total-bitcoins"]:
    url = f"https://api.blockchain.info/charts/{chart}?timespan=all&format=json&sampled=false"
    r = get(url)
    if not r: continue
    vals = r.json()["values"]
    rows = [[datetime.fromtimestamp(p["x"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), p["y"]] for p in vals]
    save_csv(f"bi_{chart}", rows, ["ts", "value"])
    manifest["charts"][f"bi_{chart}"]["source"] = "blockchain.info API"
    time.sleep(1.2)

# ---------- 3. alternative.me Fear & Greed (2018+) ----------
print("== Fear & Greed ==")
r = get("https://api.alternative.me/fng/?limit=3000&format=json")
if r:
    rows = [[datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"), d["value"], d["value_classification"]] for d in r.json()["data"]]
    save_csv("fear_greed", rows, ["date", "value", "classification"])
    manifest["charts"]["fear_greed"]["source"] = "alternative.me"

# ---------- 4. Yahoo DXY + 10y (with 429 backoff) ----------
print("== Yahoo DXY + TNX ==")
for sym, name in [("DX-Y.NYB", "dxy"), ("%5ETNX", "us10y")]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=15y&interval=1d"
    r = get(url, base_wait=8)
    if not r: continue
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]; cl = res["indicators"]["quote"][0]["close"]
    rows = [[datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"), c] for t, c in zip(ts, cl) if c is not None]
    save_csv(name, rows, ["date", "close"])
    manifest["charts"][name]["source"] = "Yahoo Finance"
    time.sleep(8)

# ---------- 5. ECB EURUSD reference (DXY proxy, 1999+) ----------
print("== ECB EURUSD ==")
r = get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml")
if r:
    root = ET.fromstring(r.text)
    ns = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
    rows = []
    for cube in root.findall(".//e:Cube/e:Cube", ns):
        d = cube.get("time")
        for c in cube.findall("e:Cube", ns):
            if c.get("currency") == "USD":
                rows.append([d, c.get("rate")])
    # hist-90d only gives 90 days; full history needs daily pulls - for now 90d
    save_csv("ecb_eurusd", rows, ["date", "rate"])
    manifest["charts"]["ecb_eurusd"]["source"] = "ECB eurofxref (90d window only - needs cron for full)"

# ---------- 6. Bitstamp ETHUSD daily (alt correlation) ----------
print("== Bitstamp ETHUSD daily ==")
rows = []
start = int(datetime.now(timezone.utc).timestamp())
while True:
    url = f"https://www.bitstamp.net/api/v2/ohlc/ethusd/?step={step}&limit=1000&start={start}"
    r = get(url)
    if not r: break
    ohlc = r.json()["data"]["ohlc"]
    if not ohlc: break
    for o in ohlc:
        rows.append([datetime.fromtimestamp(int(o["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"),
                     o["open"], o["high"], o["low"], o["close"], o["volume"]])
    oldest = int(ohlc[0]["timestamp"])
    if len(ohlc) < 1000: break
    start = oldest - step
    time.sleep(0.6)
rows = sorted(set(tuple(r) for r in rows))
save_csv("ethusd_daily_bitstamp", sorted(rows), ["date","open","high","low","close","volume"])
manifest["charts"]["ethusd_daily_bitstamp"]["source"] = "Bitstamp API v2 ohlc step=86400"

# ---------- Manifest ----------
with open(OUT / "manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)
print(f"\nDONE. {len(manifest['charts'])} charts in {OUT}")
for k, v in manifest["charts"].items():
    print(f"  {k}: {v['rows']} rows, {v.get('span','')}")
