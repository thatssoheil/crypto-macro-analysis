#!/usr/bin/env python3
"""
MACRO + CRYPTO MASTER DATASET BUILDER
All keyless sources verified 2026-08-03. FRED runs when FRED_API_KEY env is set.
Output: data/macro_dataset/<name>.csv + manifest.json + README.md
"""
import requests, json, time, csv, os, sys
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).parent.parent / "data" / "macro_dataset"
OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) dataset-builder"}
# Seed manifest from the previous build: charts that fail to fetch keep their
# old entry (and their file) instead of silently vanishing or being gutted.
_charts = {}
if (OUT / "manifest.json").exists():
    try:
        _charts = json.loads((OUT / "manifest.json").read_text()).get("charts", {})
    except Exception:
        pass
manifest = {"built": datetime.now(timezone.utc).isoformat(), "charts": _charts}
FAILED = []
FRED_KEY = os.environ.get("FRED_API_KEY", "")

def get(url, tries=4, base_wait=5):
    for i in range(tries):
        try:
            r = requests.get(url, timeout=45, headers=UA)
            if r.status_code == 200: return r
            if r.status_code == 429:
                w = base_wait * (i + 1) * 2
                print(f"    429, waiting {w}s..."); time.sleep(w); continue
            print(f"    HTTP {r.status_code}"); return None
        except Exception as e:
            print(f"    err {type(e).__name__}, retry"); time.sleep(base_wait)
    return None

def save_csv(name, rows, header, source):
    if not rows:
        FAILED.append(name)
        print(f"  WARN {name}: fetch returned no data - keeping existing file, no manifest update")
        return
    path = OUT / f"{name}.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    span = f"{rows[0][0]} -> {rows[-1][0]}" if rows else ""
    manifest["charts"][name] = {"file": path.name, "rows": len(rows), "source": source, "span": span}
    print(f"  saved {name}.csv ({len(rows)} rows, {span})")

def merge_csv(name, rows, header, source):
    """Merge-by-date writer for ROLLING-WINDOW sources.

    Glassnode's public endpoint only ever serves the last 30 days, so a plain
    overwrite would truncate the accumulated series every single run. Merge:
    existing rows keyed by date, new values win (revisions), ascending output.
    The chart therefore grows one day at a time and keeps its own history."""
    if not rows:
        print(f"  WARN {name}: no rows this run - existing file kept untouched")
        return 0
    path = OUT / f"{name}.csv"
    merged = {}
    if path.exists():
        with open(path, newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if row and row[0]:
                    merged[row[0]] = row
    before = len(merged)
    for row in rows:
        merged[row[0]] = [str(row[0]), row[1]]
    out = sorted(merged.values(), key=lambda r: r[0])
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(out)
    span = f"{out[0][0]} -> {out[-1][0]}"
    manifest["charts"][name] = {"file": path.name, "rows": len(out),
                                "source": source + " (merged; 30d window per fetch)", "span": span}
    print(f"  merged {name}.csv ({len(out)} rows, +{len(out) - before} new, {span})")
    return len(out) - before

def write_index():
    """Manifest + auto-generated README for the dataset folder."""
    with open(OUT / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    readme = ["# Macro + Crypto Master Dataset", "",
              f"Built: {manifest['built']}", "",
              "| Chart | Rows | Span | Source |", "|---|---|---|---|"]
    for k, v in manifest["charts"].items():
        readme.append(f"| {k} | {v['rows']} | {v['span']} | {v['source']} |")
    readme += ["", "FRED series (17) added when FRED_API_KEY env is set.",
               "On-chain `gn_*` charts: keyless Glassnode MCP, 30d window per fetch, merged by date",
               "(the local file is the history - run daily to accumulate; `--glassnode-only` is the fast path).",
               "Update cadence: re-run script; charts overwrite in place (gn_* merge in place)."]
    (OUT / "README.md").write_text("\n".join(readme))

# ========== 8. GLASSNODE MCP (keyless, rolling 30d window) ==========
# Free public MCP endpoint - no API key, no account. Reached over JSON-RPC/HTTP.
# Two facts drive the implementation:
#   1. Cloudflare fronts the endpoint: a bare client UA gets 403 "Just a moment",
#      a full browser header set (sec-ch-ua / sec-fetch-* / Origin) gets 200.
#   2. Every fetch returns AT MOST the last 30 days. Hence merge_csv, never
#      save_csv - the local file is the long history, the fetch is the delta.
# BTC-only by design; add an entry with a=ETH for the ETH engine.
GN_URL = "https://mcp.glassnode.com"
GN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "cross-site",
    "Origin": GN_URL, "Referer": GN_URL + "/",
}
GN_METRICS = {
    # chart name                     (Glassnode API endpoint, asset)
    "gn_exchange_netflow_btc":      ("/v1/metrics/transactions/transfers_volume_exchanges_net", "BTC"),  # BTC/day, + = into exchanges
    "gn_exchange_balance_btc":      ("/v1/metrics/distribution/balance_exchanges", "BTC"),               # BTC held on exchanges
    "gn_sopr":                      ("/v1/metrics/indicators/sopr", "BTC"),                              # spent output profit ratio
    "gn_nupl":                      ("/v1/metrics/indicators/net_unrealized_profit_loss", "BTC"),        # unrealised P/L ratio
    "gn_supply_in_profit_pct":      ("/v1/metrics/supply/profit_relative", "BTC"),                       # share of supply in profit
    # ETH twins for the ETH engine (same metric definitions, a=ETH). Verified live
    # keyless 2026-09-12; the BTC charts keep their original names, the twins are
    # suffixed _eth so nothing that already reads the BTC series is disturbed.
    "gn_exchange_netflow_eth":      ("/v1/metrics/transactions/transfers_volume_exchanges_net", "ETH"),
    "gn_exchange_balance_eth":      ("/v1/metrics/distribution/balance_exchanges", "ETH"),
    "gn_sopr_eth":                  ("/v1/metrics/indicators/sopr", "ETH"),
    "gn_nupl_eth":                  ("/v1/metrics/indicators/net_unrealized_profit_loss", "ETH"),
    "gn_supply_in_profit_pct_eth":  ("/v1/metrics/supply/profit_relative", "ETH"),
    # POINT-IN-TIME twins (2026-09-12). The live series above is a CURRENT best
    # estimate: entity labelling is revised retroactively (Glassnode's own PIT docs:
    # "as more heuristics or address linkages are discovered, historical metrics may
    # be adjusted"), so a flow number read today can differ from the same number read
    # at the time. Measured: BTC daily netflow differs from its PIT twin on 30/30 days
    # (mean 232%, max 1,150%, one sign flip) while ETH agrees to 0.2% - hence the
    # per-metric agreement gate in strategies/onchain_confidence.py rather than trust.
    # Live = best current estimate (describe the regime with it); PIT = what was
    # knowable then (backtest on it). Both are fetched in the same MCP session.
    "gn_exchange_netflow_btc_pit":  ("/v1/metrics/transactions/transfers_volume_exchanges_net_pit", "BTC"),
    "gn_exchange_balance_btc_pit":  ("/v1/metrics/distribution/balance_exchanges_pit", "BTC"),
    "gn_sopr_pit":                  ("/v1/metrics/indicators/sopr_pit", "BTC"),
    "gn_nupl_pit":                  ("/v1/metrics/indicators/net_unrealized_profit_loss_pit", "BTC"),
    "gn_supply_in_profit_pct_pit":  ("/v1/metrics/supply/profit_relative_pit", "BTC"),
    "gn_exchange_netflow_eth_pit":  ("/v1/metrics/transactions/transfers_volume_exchanges_net_pit", "ETH"),
    "gn_exchange_balance_eth_pit":  ("/v1/metrics/distribution/balance_exchanges_pit", "ETH"),
    "gn_sopr_eth_pit":              ("/v1/metrics/indicators/sopr_pit", "ETH"),
    "gn_nupl_eth_pit":              ("/v1/metrics/indicators/net_unrealized_profit_loss_pit", "ETH"),
    "gn_supply_in_profit_pct_eth_pit": ("/v1/metrics/supply/profit_relative_pit", "ETH"),
}

def _sse_json(text):
    """MCP streamable-HTTP replies come SSE-framed: 'event: message\\ndata: {...}'."""
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except Exception:
                pass
    try:
        return json.loads(text)
    except Exception:
        return None

GN_STATE = {"ok": 0, "fail": 0}

def fetch_glassnode():
    """One MCP session for all metrics. Returns the number of NEW rows merged
    (0 = the server answered but nothing changed, which is the normal case when
    the daily job runs twice in one day)."""
    sess = requests.Session()
    r = sess.post(GN_URL, headers=GN_HEADERS, timeout=45, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "crypto-macro-analysis", "version": "1.0"}}})
    if r.status_code != 200:
        print(f"  WARN glassnode unreachable (HTTP {r.status_code}) - on-chain charts keep existing data")
        return False
    sid = r.headers.get("mcp-session-id")
    if not sid:
        print("  WARN glassnode handshake returned no session id")
        return False
    h = dict(GN_HEADERS); h["mcp-session-id"] = sid
    sess.post(GN_URL, headers=h, timeout=30,
              json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    new_rows = 0
    for name, (ep, asset) in GN_METRICS.items():
        try:
            rr = sess.post(GN_URL, headers=h, timeout=60, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "fetch_metric",
                           "arguments": {"endpoint": ep,
                                         "params": {"a": asset, "i": "24h", "s": "1704067200"}}}})
            body = _sse_json(rr.text) or {}
            content = (body.get("result") or {}).get("content") or []
            payload = json.loads(content[0]["text"]) if content else {}
            points = payload.get("data") or []
            rows = [[str(p["date"])[:10], p["value"]] for p in points if p.get("value") is not None]
            GN_STATE["ok"] += 1
            new_rows += merge_csv(name, rows, ["date", "value"], f"Glassnode MCP {ep} [{asset}]")
        except Exception as e:
            GN_STATE["fail"] += 1
            print(f"  WARN {name}: {type(e).__name__} - keeping existing file")
    if not GN_STATE["ok"]:
        print("  WARN glassnode: no metric fetched this run (on-chain charts unchanged)")
    return new_rows


def bitstamp_ohlc(pair, step, name, header, source, max_iters=1000):
    """Walk back full history. Bitstamp 'start' is a FROM-filter: each call
    returns 1000 candles from start; set start = oldest - 1000*step."""
    rows, start = [], None
    for _ in range(max_iters):
        url = f"https://www.bitstamp.net/api/v2/ohlc/{pair}/?step={step}&limit=1000"
        if start: url += f"&start={start}"
        r = get(url)
        if not r: break
        ohlc = r.json()["data"]["ohlc"]
        if not ohlc: break
        for o in ohlc:
            rows.append([datetime.fromtimestamp(int(o["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                         o["open"], o["high"], o["low"], o["close"], o["volume"]])
        oldest = int(ohlc[0]["timestamp"])
        if len(ohlc) < 1000: break
        start = oldest - step * 1000
        time.sleep(0.6)
        if len(rows) % 5000 < 1000:
            print(f"    ...{rows[-1][0]} ({len(rows)} rows)")
    rows = sorted(set(tuple(r) for r in rows))
    save_csv(name, rows, header, source)

# ========== --glassnode-only fast path (used by the daily check) ==========
# Appends the rolling-window on-chain charts without refetching the slow
# sources (Bitstamp walks 15 years, Yahoo is rate-limited to ~8s/call).
if "--glassnode-only" in sys.argv:
    print("== Glassnode MCP on-chain append (rolling 30d window) ==")
    new_rows = fetch_glassnode()
    if new_rows:
        # only touch manifest/README when data actually moved, otherwise the
        # daily job would commit a timestamp-only bump every single day
        write_index()
    print(f"DONE. {new_rows} new on-chain row(s) merged." if new_rows else
          "DONE. no new on-chain rows (charts untouched, nothing to commit).")
    sys.exit(0 if GN_STATE["ok"] else 1)

# ========== 1. BITSTAMP: BTC daily + hourly, ETH daily, ETHBTC daily ==========
print("== Bitstamp BTCUSD daily ==")
bitstamp_ohlc("btcusd", 86400, "btcusd_daily_bitstamp", ["ts","open","high","low","close","volume"], "Bitstamp v2 ohlc")
print("== Bitstamp BTCUSD hourly ==")
bitstamp_ohlc("btcusd", 3600, "btcusd_hourly_bitstamp", ["ts","open","high","low","close","volume"], "Bitstamp v2 ohlc")
print("== Bitstamp ETHUSD daily ==")
bitstamp_ohlc("ethusd", 86400, "ethusd_daily_bitstamp", ["ts","open","high","low","close","volume"], "Bitstamp v2 ohlc")
print("== Bitstamp ETHBTC daily ==")
bitstamp_ohlc("ethbtc", 86400, "ethbtc_daily_bitstamp", ["ts","open","high","low","close","volume"], "Bitstamp v2 ohlc")

# ========== 2. BLOCKCHAIN.INFO on-chain (2009+) ==========
print("== blockchain.info on-chain ==")
for chart in ["hash-rate", "difficulty", "n-unique-addresses", "n-transactions", "market-cap", "total-bitcoins"]:
    r = get(f"https://api.blockchain.info/charts/{chart}?timespan=all&format=json&sampled=false")
    if not r: FAILED.append(f"bi_{chart}"); continue
    vals = r.json()["values"]
    rows = [[datetime.fromtimestamp(p["x"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), p["y"]] for p in vals]
    save_csv(f"bi_{chart}", rows, ["ts", "value"], "blockchain.info API")
    time.sleep(1.2)

# ========== 3. FEAR & GREED (2018+) ==========
print("== Fear & Greed ==")
r = get("https://api.alternative.me/fng/?limit=3000&format=json")
if r:
    rows = [[datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"), d["value"], d["value_classification"]] for d in r.json()["data"]]
    save_csv("fear_greed", rows, ["date", "value", "classification"], "alternative.me")
else:
    FAILED.append("fear_greed")

# ========== 4. YAHOO: macro risk assets (429 backoff, 8s spacing) ==========
print("== Yahoo macro ==")
yahoo = [("DX-Y.NYB","dxy"), ("%5ETNX","us10y"), ("%5ETYX","us30y"), ("%5EIRX","us3m"),
         ("%5EVIX","vix"), ("%5EGSPC","sp500"), ("%5EIXIC","nasdaq"), ("%5ERUT","russell2000"),
         ("GC%3DF","gold"), ("SI%3DF","silver"), ("CL%3DF","wti"), ("HG%3DF","copper")]
for sym, name in yahoo:
    r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=15y&interval=1d", base_wait=10)
    if r:
        res = r.json()["chart"]["result"][0]
        ts = res["timestamp"]; cl = res["indicators"]["quote"][0]["close"]
        rows = [[datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"), c] for t, c in zip(ts, cl) if c is not None]
        save_csv(name, rows, ["date", "close"], "Yahoo Finance")
    else:
        FAILED.append(name)
    time.sleep(8)

# ========== 5. ECB official FX (full history 1999+) ==========
print("== ECB EURUSD/USDJPY/USDCNY ==")
r = get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml")
if r:
    root = ET.fromstring(r.text)
    ns = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
    by_cur = {"USD": [], "JPY": [], "CNY": []}
    for cube in root.findall(".//e:Cube/e:Cube", ns):
        d = cube.get("time")
        if not d:  # this is a currency-rate cube (child of a dated cube)
            continue
        for c in cube.findall("e:Cube", ns):  # direct children only
            cur = c.get("currency")
            if cur in by_cur:
                by_cur[cur].append([d, c.get("rate")])
    for cur, rows in by_cur.items():
        if rows:
            save_csv(f"ecb_{cur.lower()}", rows, ["date", "rate"], "ECB eurofxref-hist")
        else:
            FAILED.append(f"ecb_{cur.lower()}")
    print("  NOTE: EURUSD is 57.6% of DXY; USDJPY & USDCNY for risk/FX regime")
else:
    FAILED.append("ecb_fx")

# ========== 6. DEFILLAMA: stablecoins + Ethereum TVL ==========
print("== DefiLlama stablecoins ==")
# Aggregate historical chart. Per-coin endpoints (stablecoincharts/{id}) are 404
# at DefiLlama (verified 2026-08-29) - the aggregate is the only working shape.
# Payload: [{"date": unix-str, "totalCirculatingUSD": {"peggedUSD": cap}}, ...]
r = get("https://stablecoins.llama.fi/stablecoincharts/all")
if r:
    try:
        pts = r.json()
    except Exception:
        pts = None
    if isinstance(pts, list) and pts and "totalCirculatingUSD" in pts[-1]:
        rows = [[datetime.fromtimestamp(int(p["date"]), tz=timezone.utc).strftime("%Y-%m-%d"),
                 p["totalCirculatingUSD"]["peggedUSD"]] for p in pts]
        save_csv("stablecoin_total_liquidity", rows, ["date", "total_cap_usd"], "DefiLlama stablecoincharts/all")
    else:
        FAILED.append("stablecoin_total_liquidity")
        print("  DefiLlama stablecoin payload unexpected shape - keeping existing file")
else:
    FAILED.append("stablecoin_total_liquidity")
    print("  DefiLlama failed, skipping")

print("== DefiLlama Ethereum chain TVL ==")
r_tvl = get("https://api.llama.fi/v2/historicalChainTvl/Ethereum")
if r_tvl:
    tvl_data = r_tvl.json()
    rows_tvl = [[datetime.fromtimestamp(p["date"], tz=timezone.utc).strftime("%Y-%m-%d"), p["tvl"]] for p in tvl_data]
    save_csv("eth_tvl_defillama", rows_tvl, ["date", "tvl_usd"], "DefiLlama historicalChainTvl/Ethereum")
else:
    FAILED.append("eth_tvl_defillama")

# ========== 7. FRED (runs when FRED_API_KEY set) ==========
FRED_SERIES = {"M2SL": "us_m2", "WALCL": "fed_balance_sheet", "DFF": "fed_funds_eff",
               "DGS2": "us2y", "DGS10": "us10y_fred", "DGS30": "us30y_fred",
               "T10YIE": "breakeven10y", "DFII10": "real_yield10y",
               "CPIAUCSL": "cpi", "PCEPI": "pce", "UNRATE": "unemployment",
               "ICSA": "jobless_claims", "PAYEMS": "nonfarm_payrolls",
               "BAMLH0A0HYM2": "hy_spread", "BAMLC0A0CM": "ig_spread"}
# NOTE: NAPM/NAPMN (ISM mfg/nonmfg) are DISCONTINUED at FRED - they always fail, excluded.
if FRED_KEY:
    print("== FRED ==")
    for sid, name in FRED_SERIES.items():
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id={sid}&api_key={FRED_KEY}&file_type=json&sort_order=asc"
        r = get(url)
        if not r: FAILED.append(f"fred_{name}"); continue
        obs = [o for o in r.json()["observations"] if o["value"] != "."]
        rows = [[o["date"], o["value"]] for o in obs]
        save_csv(f"fred_{name}", rows, ["date", "value"], f"FRED {sid}")
        time.sleep(0.5)
else:
    print("== FRED: SKIPPED (no FRED_API_KEY). 15 series ready when key provided: M2, Fed BS, rates, CPI, PCE, UNRATE, claims, payrolls, HY/IG spreads ==")

# ========== 8. GLASSNODE on-chain (keyless public MCP, rolling 30d) ==========
print("== Glassnode MCP on-chain (exchange flows, SOPR, NUPL, supply in profit) ==")
fetch_glassnode()

# ========== Manifest + README ==========
write_index()
print(f"\nDONE. {len(manifest['charts'])} charts -> {OUT}")
if FAILED:
    print(f"FAILED ({len(FAILED)}): {', '.join(sorted(FAILED))} - data left untouched; re-run when network is back")
    sys.exit(1)
