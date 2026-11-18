#!/usr/bin/env python3
"""
MACRO + CRYPTO MASTER DATASET BUILDER
All keyless sources verified 2026-08-03. FRED runs when FRED_API_KEY env is set.
Output: data/macro_dataset/<name>.csv + manifest.json + README.md
"""
import requests, json, time, csv, os, sys, io, zipfile
from datetime import date, datetime, timedelta, timezone
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
    span = f"{min(r[0] for r in rows)} -> {max(r[0] for r in rows)}" if rows else ""
    manifest["charts"][name] = {"file": path.name, "rows": len(rows), "source": source, "span": span}
    print(f"  saved {name}.csv ({len(rows)} rows, {span})")

def merge_csv(name, rows, header, source):
    """Merge-by-date writer for ROLLING-WINDOW sources.

    The Glassnode MCP serves at most the last 30 days per fetch (auth-walled
    since 2026-10-01 - set GLASSNODE_API_KEY), so a plain
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
    span = f"{min(r[0] for r in out)} -> {max(r[0] for r in out)}"
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
               "On-chain `gn_*` charts: Glassnode MCP (keyless access ended 2026-10-01; frozen unless a key is configured), 30d window per fetch, merged by date",
               "(the local file is the history - run daily to accumulate; `--glassnode-only` is the fast path).",
               "Update cadence: re-run script; charts overwrite in place (gn_* merge in place)."]
    (OUT / "README.md").write_text("\n".join(readme))

# ========== 8. GLASSNODE MCP (auth-walled 2026-10-01; skipped without a key) ==========
# Reached over JSON-RPC/HTTP; keyless access ended 2026-10-01 (OAuth sign-in or
# X-Api-Key header required now). Owner decision 2026-10-02: the paid route is
# declined - without GLASSNODE_API_KEY this section is SKIPPED and the charts
# stay frozen at their last data. Two facts still drive the implementation:
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
# 2026-10-01: the MCP moved behind auth - OAuth sign-in or an X-Api-Key header
# ("Authentication required", HTTP 401; the keyless era ended here).
# 2026-10-02: the paid route is declined (owner decision) - a key is NOT
# expected; the fetch sections below skip without one. If a key is ever set,
# X-Api-Key resumes the fetch automatically - nothing else needs changing.
if os.environ.get("GLASSNODE_API_KEY"):
    GN_HEADERS["X-Api-Key"] = os.environ["GLASSNODE_API_KEY"]
GN_TO_EXCH = "/v1/metrics/transactions/transfers_volume_to_exchanges_sum"
GN_TO_EXCH_PIT = GN_TO_EXCH + "_pit"
GN_FROM_EXCH = "/v1/metrics/transactions/transfers_volume_from_exchanges_sum"
GN_FROM_EXCH_PIT = GN_FROM_EXCH + "_pit"

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
    # 2026-09-24 source-hunt batch 1: flow-semantics context family + US spot ETF
    # flows. Same keyless MCP + rolling-30d merge + PIT twins. Units are stored AS
    # SERVED (SOURCES.md documents them); the confidence gate compares live vs pit
    # of the same series, so restatement detection is unit-invariant.
    "gn_hodler_npc_btc":            ("/v1/metrics/indicators/hodler_net_position_change", "BTC"),
    "gn_hodler_npc_btc_pit":        ("/v1/metrics/indicators/hodler_net_position_change_pit", "BTC"),
    "gn_hodler_npc_eth":            ("/v1/metrics/indicators/hodler_net_position_change", "ETH"),
    "gn_hodler_npc_eth_pit":        ("/v1/metrics/indicators/hodler_net_position_change_pit", "ETH"),
    "gn_net_realized_pl":           ("/v1/metrics/indicators/net_realized_profit_loss", "BTC"),
    "gn_net_realized_pl_pit":       ("/v1/metrics/indicators/net_realized_profit_loss_pit", "BTC"),
    "gn_net_realized_pl_eth":       ("/v1/metrics/indicators/net_realized_profit_loss", "ETH"),
    "gn_net_realized_pl_eth_pit":   ("/v1/metrics/indicators/net_realized_profit_loss_pit", "ETH"),
    "gn_sopr_adjusted":             ("/v1/metrics/indicators/sopr_adjusted", "BTC"),
    "gn_sopr_adjusted_pit":         ("/v1/metrics/indicators/sopr_adjusted_pit", "BTC"),
    "gn_sopr_155d":                 ("/v1/metrics/indicators/sopr_more_155", "BTC"),
    "gn_sopr_155d_pit":             ("/v1/metrics/indicators/sopr_more_155_pit", "BTC"),
    "gn_whales_to_exchanges":       ("/v1/metrics/transactions/transfers_volume_whales_to_exchanges_sum", "BTC"),
    "gn_whales_to_exchanges_pit":   ("/v1/metrics/transactions/transfers_volume_whales_to_exchanges_sum_pit", "BTC"),
    "gn_exchanges_to_whales":       ("/v1/metrics/transactions/transfers_volume_exchanges_to_whales_sum", "BTC"),
    "gn_exchanges_to_whales_pit":   ("/v1/metrics/transactions/transfers_volume_exchanges_to_whales_sum_pit", "BTC"),
    "gn_reshuffling_ratio":         ("/v1/metrics/distribution/exchange_reshuffling_ratio", "BTC"),
    "gn_reshuffling_ratio_pit":     ("/v1/metrics/distribution/exchange_reshuffling_ratio_pit", "BTC"),
    "gn_etf_flows_net_btc":         ("/v1/metrics/institutions/us_spot_etf_flows_net", "BTC"),
    "gn_etf_flows_net_btc_pit":     ("/v1/metrics/institutions/us_spot_etf_flows_net_pit", "BTC"),
    "gn_etf_flows_net_eth":         ("/v1/metrics/institutions/us_spot_etf_flows_net", "ETH"),
    "gn_etf_flows_net_eth_pit":     ("/v1/metrics/institutions/us_spot_etf_flows_net_pit", "ETH"),
    # 2026-09-27 batch 2: BINANCE-specific gross exchange flows (inflow and outflow
    # separately). The MCP passes query params through, so e=binance filters to the
    # venue. Gross directions are non-negative; the confidence gate treats them with
    # the level rule. All-exchange gross twins (no e filter) exist for validation but
    # are NOT committed here.
    "gn_binance_inflow_btc":        (GN_TO_EXCH, "BTC", {"e": "binance"}),
    "gn_binance_inflow_btc_pit":    (GN_TO_EXCH_PIT, "BTC", {"e": "binance"}),
    "gn_binance_outflow_btc":       (GN_FROM_EXCH, "BTC", {"e": "binance"}),
    "gn_binance_outflow_btc_pit":   (GN_FROM_EXCH_PIT, "BTC", {"e": "binance"}),
    "gn_binance_inflow_eth":        (GN_TO_EXCH, "ETH", {"e": "binance"}),
    "gn_binance_inflow_eth_pit":    (GN_TO_EXCH_PIT, "ETH", {"e": "binance"}),
    "gn_binance_outflow_eth":       (GN_FROM_EXCH, "ETH", {"e": "binance"}),
    "gn_binance_outflow_eth_pit":   (GN_FROM_EXCH_PIT, "ETH", {"e": "binance"}),
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
        if r.status_code == 401:
            print("  WARN glassnode auth failed (HTTP 401) - check GLASSNODE_API_KEY in .env; "
                  "on-chain charts keep existing data")
        else:
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
    for name, spec in GN_METRICS.items():
        ep, asset = spec[0], spec[1]
        extra = spec[2] if len(spec) > 2 else {}
        try:
            rr = sess.post(GN_URL, headers=h, timeout=60, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "fetch_metric",
                           "arguments": {"endpoint": ep,
                                         "params": {"a": asset, "i": "24h", "s": "1704067200", **extra}}}})
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

def fetch_solana():
    """SOL-USD history, venue volume, and Solana chain economics (onboarded 2026-11-18).

    Longest keyless history per chart, all verified live on 2026-11-18:
      SOL-USD daily OHLCV       Yahoo (CCC aggregate)  2020-04-10 ->  SOL spot opened April 2020;
                                                       no keyless source starts earlier.
      SOL-USDT daily OHLCV      OKX                   2020-09-29 ->  second venue print, plus the
                                                       quote (USD) volume the cross-check needs.
      Solana chain TVL          DefiLlama             2021-03-17 ->
      Solana stablecoin supply  DefiLlama             2021-09-10 ->  DAILY only from 2023; 2022 is
                                                       sparse, so calendar-anchored changes only.
      Solana DEX volume         DefiLlama             2021-10-02 ->
      Solana fees + revenue     DefiLlama             2021-01-17 ->
      SOL DVOL / OI / funding   Deribit + Binance archive (section 10; deep history via
                                strategies/backfill_derivatives.py).
    Weekly history is deliberately NOT a chart: it is a deterministic resample of the daily
    series (strategies/sol_macro_report.py), so price keeps exactly one source of truth.
    """
    print("== Solana: SOL-USD daily (Yahoo, longest series) ==")
    r = get("https://query1.finance.yahoo.com/v8/finance/chart/SOL-USD?range=10y&interval=1d", base_wait=10)
    if r:
        _res = r.json()["chart"]["result"][0]
        _q = _res["indicators"]["quote"][0]
        rows = []
        for _t, _o, _h, _l, _c, _v in zip(_res["timestamp"], _q["open"], _q["high"], _q["low"],
                                          _q["close"], _q["volume"]):
            if _c is None:
                continue
            rows.append([datetime.fromtimestamp(_t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                         _o, _h, _l, _c, _v if _v is not None else 0])
        save_csv("solusd_daily_yahoo", rows, ["ts", "open", "high", "low", "close", "volume"],
                 "Yahoo Finance SOL-USD (CCC aggregate)")
    else:
        FAILED.append("solusd_daily_yahoo")
    time.sleep(8)

    print("== Solana: SOL-USDT daily (OKX venue print + USD volume) ==")
    rows, after, _calls = [], None, 0
    while _calls < 60:
        params = f"instId=SOL-USDT&bar=1D&limit=100" + (f"&after={after}" if after else "")
        rr = get(f"https://www.okx.com/api/v5/market/history-candles?{params}", tries=3)
        data = (rr.json().get("data") or []) if rr else []
        if not data:
            break
        for c in data:
            rows.append([datetime.fromtimestamp(int(c[0]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                         c[1], c[2], c[3], c[4], c[5], c[7]])
        after = data[-1][0]
        _calls += 1
        if len(data) < 100:
            break
        time.sleep(0.25)
    save_csv("solusd_daily_okx", sorted(set(tuple(x) for x in rows)),
             ["ts", "open", "high", "low", "close", "volume", "volume_usd"],
             "OKX v5 history-candles SOL-USDT (1D)")

    print("== Solana: chain TVL (DefiLlama) ==")
    r = get("https://api.llama.fi/v2/historicalChainTvl/Solana")
    if r:
        rows = [[datetime.fromtimestamp(p["date"], tz=timezone.utc).strftime("%Y-%m-%d"), p["tvl"]]
                for p in r.json()]
        save_csv("sol_tvl_defillama", rows, ["date", "tvl_usd"],
                 "DefiLlama historicalChainTvl/Solana")
    else:
        FAILED.append("sol_tvl_defillama")

    print("== Solana: stablecoin supply on Solana (DefiLlama) ==")
    r = get("https://stablecoins.llama.fi/stablecoincharts/Solana")
    rows = []
    if r:
        try:
            for p in r.json():
                v = (p.get("totalCirculatingUSD") or {}).get("peggedUSD")
                if v is None:
                    continue
                rows.append([datetime.fromtimestamp(int(p["date"]), tz=timezone.utc).strftime("%Y-%m-%d"), v])
        except Exception:
            rows = []
    if rows:
        save_csv("sol_stablecoins_defillama", rows, ["date", "usd"],
                 "DefiLlama stablecoincharts/Solana (peggedUSD circulating)")
    else:
        FAILED.append("sol_stablecoins_defillama")

    print("== Solana: DEX volume (DefiLlama) ==")
    r = get("https://api.llama.fi/overview/dexs/solana?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=true")
    rows = []
    if r:
        try:
            rows = [[datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d"), v]
                    for ts, v in (r.json().get("totalDataChart") or [])]
        except Exception:
            rows = []
    if rows:
        save_csv("sol_dex_volume_defillama", rows, ["date", "usd"],
                 "DefiLlama overview/dexs/solana (daily DEX volume)")
    else:
        FAILED.append("sol_dex_volume_defillama")

    print("== Solana: chain fees + revenue (DefiLlama) ==")
    # fees = what users paid; revenue = the burned/retained share. Two payloads, one chart.
    _fees, _rev = {}, {}
    r = get("https://api.llama.fi/summary/fees/solana?dataType=dailyFees")
    if r:
        for ts, v in (r.json().get("totalDataChart") or []):
            _fees[datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")] = v
    r = get("https://api.llama.fi/summary/fees/solana?dataType=dailyRevenue")
    if r:
        for ts, v in (r.json().get("totalDataChart") or []):
            _rev[datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")] = v
    rows = [[d0, _fees.get(d0, ""), _rev.get(d0, "")] for d0 in sorted(set(_fees) | set(_rev))]
    if rows:
        save_csv("sol_fees_defillama", rows, ["date", "fees_usd", "revenue_usd"],
                 "DefiLlama summary/fees/solana (dailyFees + dailyRevenue)")
    else:
        FAILED.append("sol_fees_defillama")

    print("== Solana: SOL/BTC venue pair (OKX) ==")
    # The actual traded cross, not a computed ratio: it carries its own price and
    # quote volume, so a stale or thin print is visible (zero-volume days = 0 in
    # the full history, verified 2026-11-18). The engine still computes SOL/BTC
    # from aligned USD closes for signals; this chart is the venue truth to check it.
    rows, after, _calls = [], None, 0
    while _calls < 60:
        params = "instId=SOL-BTC&bar=1D&limit=100" + (f"&after={after}" if after else "")
        rr = get(f"https://www.okx.com/api/v5/market/history-candles?{params}", tries=3)
        data = (rr.json().get("data") or []) if rr else []
        if not data:
            break
        for c in data:
            rows.append([datetime.fromtimestamp(int(c[0]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                         c[1], c[2], c[3], c[4], c[5], c[7]])
        after = data[-1][0]
        _calls += 1
        if len(data) < 100:
            break
        time.sleep(0.25)
    save_csv("solbtc_daily_okx", sorted(set(tuple(x) for x in rows)),
             ["ts", "open", "high", "low", "close", "volume", "volume_usd"],
             "OKX v5 history-candles SOL-BTC (1D, traded cross)")

    print("== Solana: market cap + total crypto market cap (CoinMarketCap data-api) ==")
    # SOL.D (Solana dominance) needs BOTH sides: SOL's market cap and the total crypto
    # market cap. CoinGecko refuses both keyless (global chart is PRO-only, market_chart
    # caps at 365 days), so we use CMC's public data-api, which answers keyless but only
    # in chunks - 350 days per call, otherwise it silently samples. Verified 2026-11-18.
    _CMC_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
               "Accept": "application/json"}

    def _cmc_quotes(url, base, start="2020-04-10", chunk_days=350):
        out, cur = [], datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.now(timezone.utc)
        while cur < end:
            nxt = min(cur + timedelta(days=chunk_days), end)
            params = dict(base, timeStart=int(cur.timestamp()), timeEnd=int(nxt.timestamp()))
            payload = None
            for attempt in range(3):
                try:
                    rr = requests.get(url, params=params, headers=_CMC_UA, timeout=45)
                    if rr.status_code == 200:
                        payload = rr.json().get("data")
                        if payload:
                            break
                except Exception:
                    pass
                time.sleep(2 * (attempt + 1))
            if payload:
                out.extend(payload.get("quotes") or [])
            else:
                print(f"    CMC chunk {cur:%Y-%m-%d} failed")
            cur = nxt
            time.sleep(1.2)
        return out

    _sol_hist = _cmc_quotes("https://api.coinmarketcap.com/data-api/v3/cryptocurrency/historical",
                            {"id": "5426", "convertId": "2781", "interval": "1d"})
    # chunk boundaries repeat a day (timeStart/timeEnd are both inclusive) - key by date
    _by_date = {}
    for q in _sol_hist:
        d0 = q.get("timeOpen", "")[:10]
        qq = q.get("quote") or {}
        if not d0 or qq.get("close") is None:
            continue
        _by_date[d0] = [d0, qq.get("open"), qq.get("high"), qq.get("low"), qq.get("close"),
                        qq.get("volume"), qq.get("marketCap"), qq.get("circulatingSupply")]
    _rows = [_by_date[k] for k in sorted(_by_date)]
    if _rows:
        save_csv("sol_mcap_cmc", _rows,
                 ["date", "open", "high", "low", "close", "volume_usd", "mcap_usd", "supply"],
                 "CoinMarketCap data-api cryptocurrency/historical id=5426 (daily)")
    else:
        FAILED.append("sol_mcap_cmc")

    _glob_hist = _cmc_quotes("https://api.coinmarketcap.com/data-api/v3/global-metrics/quotes/historical",
                             {"convertId": "2781", "interval": "1d"})
    _by_date = {}
    for q in _glob_hist:
        d0 = q.get("timestamp", "")[:10]
        qq = (q.get("quote") or [{}])[0]
        if not d0 or qq.get("totalMarketCap") is None:
            continue
        _by_date[d0] = [d0, qq.get("totalMarketCap"), q.get("btcDominance"), q.get("ethDominance")]
    _rows = [_by_date[k] for k in sorted(_by_date)]
    if _rows:
        save_csv("cmc_total_mcap", _rows,
                 ["date", "total_mcap_usd", "btc_dominance", "eth_dominance"],
                 "CoinMarketCap data-api global-metrics/quotes/historical (daily)")
    else:
        FAILED.append("cmc_total_mcap")

    # SOL.D = SOL market cap / total crypto market cap. Derived, so it is rebuilt from
    # the two committed inputs on every run and can never disagree with them.
    print("== Solana: SOL.D dominance (derived from the two charts above) ==")
    try:
        _sol_rows = {}
        with open(OUT / "sol_mcap_cmc.csv", newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if row and row[0] and float(row[6] or 0) > 0:
                    _sol_rows[row[0]] = float(row[6])
        _tot_rows = {}
        with open(OUT / "cmc_total_mcap.csv", newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if row and row[0] and float(row[1] or 0) > 0:
                    _tot_rows[row[0]] = float(row[1])
        dom = [[d0, round(_sol_rows[d0] / _tot_rows[d0] * 100, 4)]
               for d0 in sorted(set(_sol_rows) & set(_tot_rows))]
        if dom:
            save_csv("sol_dominance", dom, ["date", "pct"],
                     "derived: sol_mcap_cmc / cmc_total_mcap * 100")
        else:
            FAILED.append("sol_dominance")
    except Exception as exc:
        FAILED.append("sol_dominance")
        print(f"  WARN sol_dominance: {type(exc).__name__}")

    print("== Solana: SOL/ETH (derived from aligned USD closes) ==")
    try:
        _sol = {}
        with open(OUT / "solusd_daily_yahoo.csv", newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if row and row[0]:
                    _sol[row[0][:10]] = float(row[4])
        _eth = {}
        with open(OUT / "ethusd_daily_bitstamp.csv", newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if row and row[0]:
                    _eth[row[0][:10]] = float(row[4])
        common = sorted(set(_sol) & set(_eth))
        rows = [[f"{d0} 00:00:00", round(_sol[d0] / _eth[d0], 6)] for d0 in common]
        if rows:
            save_csv("soleth_daily", rows, ["ts", "close"],
                     "derived from solusd_daily_yahoo / ethusd_daily_bitstamp closes")
        else:
            FAILED.append("soleth_daily")
    except Exception as exc:
        FAILED.append("soleth_daily")
        print(f"  WARN soleth_daily: {type(exc).__name__}")


def fetch_zec():
    """ZEC history: longest traded series, the BTC cross, dominance and supply.

    ZEC launched 2016-10-28, so the history is deeper than SOL's and includes the
    2017 bull, the 2018-2020 bear and the 2024-2026 privacy run.
      zecusd_daily_bitfinex   2016-10-29 ->  longest ZEC/USD daily series that exists
      zecbtc_daily_bitfinex   2016-10-28 ->  the traded BTC cross, same length
      zecusd_daily_okx        2025-11-23 ->  OKX only listed ZEC-USDT recently, but it is
                                              the venue that carries real quote volume and
                                              the swap the liquidation model needs
      zec_mcap_cmc            2016-10-29 ->  price, volume, market cap, supply (CMC data-api)
      zec_dominance           2020-04-10 ->  derived: zec_mcap / cmc_total_mcap (the total-cap
                                              chart starts 2020-04, so dominance does too)
      zeceth_daily            2016-10-29 ->  derived from USD closes (no traded ZEC/ETH pair)
    LAUNCH ARTIFACT: ZEC's first prints on Bitfinex (2016-10-29) were 3,591 USD on slow-start
    supply, so the all-time high on a raw series is meaningless. Any drawdown read must start
    2017-01-01 or use a post-launch high - the state study takes --start for this reason.
    """
    print("== Zcash: ZEC/USD + ZEC/BTC daily (Bitfinex, longest series) ==")
    for sym, name, header, src in (
        ("tZECUSD", "zecusd_daily_bitfinex", ["ts", "open", "high", "low", "close", "volume"],
         "Bitfinex v2 candles trade:1D:tZECUSD"),
        ("tZECBTC", "zecbtc_daily_bitfinex", ["ts", "open", "high", "low", "close", "volume"],
         "Bitfinex v2 candles trade:1D:tZECBTC (traded cross)"),
    ):
        r = get(f"https://api-pub.bitfinex.com/v2/candles/trade:1D:{sym}/hist?limit=10000&sort=1",
                tries=3)
        rows = []
        if r:
            try:
                for c in r.json():
                    # Bitfinex order: MTS, OPEN, CLOSE, HIGH, LOW, VOLUME
                    rows.append([datetime.fromtimestamp(int(c[0]) / 1000, tz=timezone.utc)
                                 .strftime("%Y-%m-%d %H:%M:%S"), c[1], c[3], c[4], c[2], c[5]])
            except Exception:
                rows = []
        if rows:
            save_csv(name, rows, header, src)
        else:
            FAILED.append(name)
        time.sleep(1.5)

    print("== Zcash: ZEC/USDT recent venue print (OKX) ==")
    rows, after, _calls = [], None, 0
    while _calls < 40:
        params = "instId=ZEC-USDT&bar=1D&limit=100" + (f"&after={after}" if after else "")
        rr = get(f"https://www.okx.com/api/v5/market/history-candles?{params}", tries=3)
        data = (rr.json().get("data") or []) if rr else []
        if not data:
            break
        for c in data:
            rows.append([datetime.fromtimestamp(int(c[0]) / 1000, tz=timezone.utc)
                         .strftime("%Y-%m-%d %H:%M:%S"), c[1], c[2], c[3], c[4], c[5], c[7]])
        after = data[-1][0]
        _calls += 1
        if len(data) < 100:
            break
        time.sleep(0.25)
    save_csv("zecusd_daily_okx", sorted(set(tuple(x) for x in rows)),
             ["ts", "open", "high", "low", "close", "volume", "volume_usd"],
             "OKX v5 history-candles ZEC-USDT (1D)")

    print("== Zcash: market cap and supply (CoinMarketCap data-api) ==")
    _CMC_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
               "Accept": "application/json"}

    def _cmc(url, base, start, chunk_days=350):
        out, cur = [], datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.now(timezone.utc)
        while cur < end:
            nxt = min(cur + timedelta(days=chunk_days), end)
            params = dict(base, timeStart=int(cur.timestamp()), timeEnd=int(nxt.timestamp()))
            payload = None
            for attempt in range(3):
                try:
                    rr = requests.get(url, params=params, headers=_CMC_UA, timeout=45)
                    if rr.status_code == 200:
                        payload = rr.json().get("data")
                        if payload:
                            break
                except Exception:
                    pass
                time.sleep(2 * (attempt + 1))
            if payload:
                out.extend(payload.get("quotes") or [])
            cur = nxt
            time.sleep(1.2)
        return out

    _hist = _cmc("https://api.coinmarketcap.com/data-api/v3/cryptocurrency/historical",
                 {"id": "1437", "convertId": "2781", "interval": "1d"}, "2016-10-28")
    _by_date = {}
    for q in _hist:
        d0 = q.get("timeOpen", "")[:10]
        qq = q.get("quote") or {}
        if not d0 or qq.get("close") is None:
            continue
        _by_date[d0] = [d0, qq.get("open"), qq.get("high"), qq.get("low"), qq.get("close"),
                        qq.get("volume"), qq.get("marketCap"), qq.get("circulatingSupply")]
    if _by_date:
        save_csv("zec_mcap_cmc", [_by_date[k] for k in sorted(_by_date)],
                 ["date", "open", "high", "low", "close", "volume_usd", "mcap_usd", "supply"],
                 "CoinMarketCap data-api cryptocurrency/historical id=1437 (daily)")
    else:
        FAILED.append("zec_mcap_cmc")

    print("== Zcash: ZEC.D dominance + ZEC/ETH (derived) ==")
    try:
        zec_mc, tot_mc, zec_usd, eth_usd = {}, {}, {}, {}
        with open(OUT / "zec_mcap_cmc.csv", newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if row and row[0] and float(row[6] or 0) > 0:
                    zec_mc[row[0]] = float(row[6])
        with open(OUT / "cmc_total_mcap.csv", newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if row and row[0] and float(row[1] or 0) > 0:
                    tot_mc[row[0]] = float(row[1])
        dom = [[d0, round(zec_mc[d0] / tot_mc[d0] * 100, 5)]
               for d0 in sorted(set(zec_mc) & set(tot_mc))]
        if dom:
            save_csv("zec_dominance", dom, ["date", "pct"],
                     "derived: zec_mcap_cmc / cmc_total_mcap * 100")
        with open(OUT / "zecusd_daily_bitfinex.csv", newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if row and row[0]:
                    zec_usd[row[0][:10]] = float(row[4])
        with open(OUT / "ethusd_daily_bitstamp.csv", newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if row and row[0]:
                    eth_usd[row[0][:10]] = float(row[4])
        common = sorted(set(zec_usd) & set(eth_usd))
        rows = [[f"{d0} 00:00:00", round(zec_usd[d0] / eth_usd[d0], 6)] for d0 in common]
        if rows:
            save_csv("zeceth_daily", rows, ["ts", "close"],
                     "derived from zecusd_daily_bitfinex / ethusd_daily_bitstamp closes")
    except Exception as exc:
        print(f"  WARN zec derived charts: {type(exc).__name__}")
        FAILED.append("zec_dominance")


# ========== --solana-only fast path ==========
# Solana onboarding runs alone: the full builder walks Bitstamp back to 2011 and
# Yahoo at 8s per symbol, which is minutes of network for charts that did not change.
if "--solana-only" in sys.argv:
    fetch_solana()
    write_index()
    print(f"\nDONE (solana only). {len(manifest['charts'])} charts -> {OUT}")
    if FAILED:
        print(f"FAILED ({len(FAILED)}): {', '.join(sorted(FAILED))}")
        sys.exit(1)
    sys.exit(0)

# ========== --zec-only fast path ==========
if "--zec-only" in sys.argv:
    fetch_zec()
    write_index()
    print(f"\nDONE (zec only). {len(manifest['charts'])} charts -> {OUT}")
    if FAILED:
        print(f"FAILED ({len(FAILED)}): {', '.join(sorted(FAILED))}")
        sys.exit(1)
    sys.exit(0)

# ========== --glassnode-only fast path (used by the daily check) ==========
# Appends the rolling-window on-chain charts without refetching the slow
# sources (Bitstamp walks 15 years, Yahoo is rate-limited to ~8s/call).
if "--glassnode-only" in sys.argv:
    if not os.environ.get("GLASSNODE_API_KEY"):
        # 2026-10-02: keyless access ended 2026-10-01 and the paid route is
        # declined - with no key there is nothing to append (skip, exit 0).
        print("== Glassnode on-chain: SKIPPED (no key; keyless access ended 2026-10-01, paid route declined) ==")
        sys.exit(0)
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
r = get("https://api.alternative.me/fng/?limit=0&format=json")
if not r:
    r = get("https://api.alternative.me/fng/?limit=3000&format=json")
try:
    fng_payload = r.json()["data"] if r else []
except Exception:
    fng_payload = []
if fng_payload:
    # Fixed 2026-11-04: limit=3000 + overwrite made this file a rolling window that ate its
    # own history (it started 2018-08-15 and had started 2018-08-01 three commits earlier).
    # limit=0 asks for everything available, and the result is MERGED by date into the
    # committed file, so the early 2018 bear can never be lost again.
    fetched = [[datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d"),
                str(d["value"]), d["value_classification"]] for d in fng_payload]
    path = OUT / "fear_greed.csv"
    merged = {}
    if path.exists():
        with open(path, newline="") as f:
            rd = csv.reader(f); next(rd, None)
            for row in rd:
                if row and row[0]:
                    merged[row[0]] = row
    before = len(merged)
    for row in fetched:
        merged[row[0]] = row
    out = sorted(merged.values(), key=lambda x: x[0])
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "value", "classification"]); w.writerows(out)
    span = f"{out[0][0]} -> {out[-1][0]}"
    manifest["charts"]["fear_greed"] = {"file": "fear_greed.csv", "rows": len(out),
                                        "source": "alternative.me (merged; history preserved)",
                                        "span": span}
    print(f"  merged fear_greed.csv ({len(out)} rows, +{len(out) - before} new, {span})")
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
               "BAMLH0A0HYM2": "hy_spread", "BAMLC0A0CM": "ig_spread",
               # 2026-09-24 (liquidity batch): the money-plumbing pair. RRP = the
               # Fed's reverse-repo pool (the buffer that drains first), TGA =
               # Treasury's cash at the Fed (a rebuild drains reserves). Enables the
               # net-liquidity read: Fed BS - TGA - RRP (daily TGA in section 9).
               "RRPONTSYD": "rrp", "WTREGEN": "tga"}
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
    print("== FRED: SKIPPED (no FRED_API_KEY). 17 series ready when key provided: M2, Fed BS, rates, CPI, PCE, UNRATE, claims, payrolls, HY/IG spreads, RRP/TGA ==")

# ========== 8. GLASSNODE on-chain (auth-walled 2026-10-01; skipped without a key) ==========
if os.environ.get("GLASSNODE_API_KEY"):
    print("== Glassnode MCP on-chain (exchange flows, SOPR, NUPL, supply in profit) ==")
    fetch_glassnode()
else:
    print("== Glassnode on-chain: SKIPPED (no key; keyless access ended 2026-10-01, paid route declined) - charts keep existing data ==")

# ========== 9. TREASURY FISCALDATA: daily TGA (keyless) ==========
# Daily counterpart of FRED's weekly WTREGEN, for the net-liquidity read
# (Fed BS - TGA - RRP). The history has three naming eras (verified 2026-09-24):
#   2010-01..2021-09  "Federal Reserve Account"                (close_today_bal)
#   2021-10..2022-04  "Treasury General Account (TGA)"         (close_today_bal)
#   2022-04..now      "Treasury General Account (TGA) Closing Balance"
#                     (close_today_bal is null in this feed - the value sits in
#                      open_today_bal; verified against the $957B figure)
# Values are USD millions, stored as served.
print("== Treasury FiscalData daily TGA ==")
import re as _re
_FD = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
       "/v1/accounting/dts/operating_cash_balance")
_tga_pat = _re.compile(r"^(Treasury General Account \(TGA\)( Closing Balance)?|Federal Reserve Account)$")
def _num(x):
    """FiscalData serves the STRING 'null' for missing values in some rows."""
    if x in (None, "", "null"):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
_tga, _ok = {}, True
for _page in (1, 2, 3):
    r = get(f"{_FD}?sort=record_date&page[size]=10000&page[number]={_page}")
    if not r:
        _ok = False
        break
    _data = r.json().get("data") or []
    for d in _data:
        if not _tga_pat.match(d.get("account_type", "")):
            continue
        v = _num(d.get("close_today_bal"))
        if v is None:
            v = _num(d.get("open_today_bal"))
        if v is None:
            continue
        _tga[d["record_date"]] = v
    if len(_data) < 10000:
        break
if _ok and _tga:
    rows = [[d, _tga[d]] for d in sorted(_tga)]
    save_csv("tga_daily", rows, ["date", "value"],
             "Treasury FiscalData DTS operating cash balance (TGA, USD millions)")
else:
    FAILED.append("tga_daily")

# ========== 10. DERIVATIVES: Deribit DVOL + Binance archive positioning ==========
# Keyless pair (source-hunt batch 2b, added 2026-09-24). Replaces the planned
# Glassnode derivatives batch (the public MCP went OAuth-only mid-day).
#   - Deribit public API: DVOL daily closes (BTC/ETH). We fetch the last ~1000
#     days and merge (the local file is the long history).
#   - Binance USD-M daily metrics zips (data.binance.vision, append-only archive):
#     perp open interest, top-trader long/short ratio, taker buy/sell ratio.
#     Fetch only missing days (3-day overlap, bounded to 60/run) and merge.
#   - Binance monthly fundingRate zips: daily SUMS of the 8h rates (~1 month lag -
#     the current month's file lands after month end).
# Deep history: strategies/backfill_derivatives.py (one-time). Committed CSVs = history.
print("== Derivatives: Deribit DVOL ==")
_DERIBIT = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
_dvol_start = int((datetime.now(timezone.utc) - timedelta(days=1000)).timestamp() * 1000)
for _cur, _name in (("BTC", "dvol_btc"), ("ETH", "dvol_eth")):   # SOL DVOL died 2022-11-25
    try:
        r = get(f"{_DERIBIT}?currency={_cur}&start_timestamp={_dvol_start}&end_timestamp={int(time.time()*1000)}&resolution=1D", tries=2)
        pts = ((r.json().get("result") or {}).get("data") or []) if r else []
        rows = [[datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"), p[4]] for p in pts]
        if rows:
            merge_csv(_name, rows, ["date", "value"], "Deribit DVOL (daily close)")
        else:
            FAILED.append(_name)
    except Exception as e:
        FAILED.append(_name)
        print(f"  WARN {_name}: {type(e).__name__}")

print("== Derivatives: Binance perp positioning (daily archive) ==")
_BZ = "https://data.binance.vision"
_METRIC_COLS = {"sum_open_interest": "oi",
                "sum_toptrader_long_short_ratio": "lsr",
                "sum_taker_long_short_vol_ratio": "taker"}
_METRIC_ORDER = ["create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
                 "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
                 "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]

def _last_csv_date(name):
    p = OUT / f"{name}.csv"
    if not p.exists():
        return None
    with open(p, newline="") as f:
        rows = [r for r in csv.reader(f) if r and r[0] and r[0] != "date"]
    return rows[-1][0] if rows else None

for _sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT"):
    _asset = _sym[:3].lower()
    _have = [_last_csv_date(f"bn_{_suf}_{_asset}") for _suf in _METRIC_COLS.values()]
    _have = [d for d in _have if d]
    if _have:
        _d = datetime.strptime(max(_have), "%Y-%m-%d").date() - timedelta(days=3)  # overlap
    else:
        _d = date.today() - timedelta(days=30)
    _d = max(_d, date.today() - timedelta(days=60))
    _end = date.today()
    _acc = {s: [] for s in _METRIC_COLS.values()}
    _fetched = 0
    while _d < _end and _fetched < 60:
        _ds = _d.isoformat()
        try:
            r = get(f"{_BZ}/data/futures/um/daily/metrics/{_sym}/{_sym}-metrics-{_ds}.zip", tries=2)
            if r is not None:
                z = zipfile.ZipFile(io.BytesIO(r.content))
                _lines = [l for l in z.read(z.namelist()[0]).decode().splitlines() if l.strip()]
                if _lines and _lines[0].startswith("create_time"):
                    _idx = {h: i for i, h in enumerate(_lines[0].split(","))}
                    _rows = _lines[1:]
                else:
                    _idx = {h: i for i, h in enumerate(_METRIC_ORDER)}
                    _rows = _lines
                _lastrow = _rows[-1].split(",")
                for _col, _suf in _METRIC_COLS.items():
                    try:
                        _acc[_suf].append([_ds, float(_lastrow[_idx[_col]])])
                    except (ValueError, IndexError, KeyError):
                        pass
                _fetched += 1
        except Exception:
            pass
        _d += timedelta(days=1)
        time.sleep(0.05)
    for _suf in _METRIC_COLS.values():
        _name = f"bn_{_suf}_{_asset}"
        if _acc[_suf]:
            merge_csv(_name, _acc[_suf], ["date", "value"], f"Binance USD-M daily metrics ({_sym})")
        else:
            FAILED.append(_name)

print("== Derivatives: Binance funding (monthly archive) ==")
_months = []
_m = date.today().replace(day=1)
for _ in range(2):
    _m = (_m - timedelta(days=1)).replace(day=1)
    _months.append(_m)
for _sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ZECUSDT"):
    _asset = _sym[:3].lower()
    _acc = []
    for _m in _months:
        _ms = f"{_m.year:04d}-{_m.month:02d}"
        try:
            r = get(f"{_BZ}/data/futures/um/monthly/fundingRate/{_sym}/{_sym}-fundingRate-{_ms}.zip", tries=2)
            if r is not None:
                z = zipfile.ZipFile(io.BytesIO(r.content))
                _lines = [l for l in z.read(z.namelist()[0]).decode().splitlines() if l.strip()]
                if _lines and _lines[0].startswith("calc_time"):
                    _idx = {h: i for i, h in enumerate(_lines[0].split(","))}
                    _rows = _lines[1:]
                else:
                    _idx = {h: i for i, h in enumerate(["calc_time", "funding_interval_hours", "last_funding_rate"])}
                    _rows = _lines
                _sums = {}
                for _l in _rows:
                    _parts = _l.split(",")
                    # calc_time is UNIX MILLISECONDS (not a date string)
                    _day = datetime.fromtimestamp(int(_parts[_idx["calc_time"]]) / 1000,
                                                 tz=timezone.utc).strftime("%Y-%m-%d")
                    _sums[_day] = _sums.get(_day, 0.0) + float(_parts[_idx["last_funding_rate"]])
                _acc += [[k, v] for k, v in _sums.items()]
        except Exception:
            pass
        time.sleep(0.05)
    if _acc:
        merge_csv(f"bn_funding_{_asset}", _acc, ["date", "value"], f"Binance monthly fundingRate ({_sym}, daily sums)")
    else:
        FAILED.append(f"bn_funding_{_asset}")

# ========== 11. SOLANA (onboarded 2026-11-18) ==========
# Runs BEFORE Zcash: the ZEC dominance chart divides by cmc_total_mcap, which the
# Solana block fetches.
print("== SOLANA: price, venue volume, chain economics ==")
fetch_solana()

# ========== 12. ZCASH (onboarded 2026-11-18) ==========
print("== ZCASH: price, cross, dominance, supply ==")
fetch_zec()

# ========== Manifest + README ==========
write_index()
print(f"\nDONE. {len(manifest['charts'])} charts -> {OUT}")
if FAILED:
    print(f"FAILED ({len(FAILED)}): {', '.join(sorted(FAILED))} - data left untouched; re-run when network is back")
    sys.exit(1)
