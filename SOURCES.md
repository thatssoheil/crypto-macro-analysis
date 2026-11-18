# Data Sources

Every series in `data/macro_dataset/` (119 charts) and where it comes from.
All sources are keyless unless marked. Re-fetch with `bash scripts/refresh.sh`
or `python strategies/build_macro_dataset.py`.

## Crypto price (Bitstamp)

| Chart | Source | Endpoint | Span | Notes |
|-------|--------|----------|------|-------|
| `btcusd_daily_bitstamp` | Bitstamp v2 OHLC | `https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=86400&limit=1000` | 2011-08+ | True daily. `start` param is a FROM-filter - page with `start = oldest - step*1000`. |
| `btcusd_hourly_bitstamp` | Bitstamp v2 OHLC | `.../ohlc/btcusd/?step=3600` | 2011-08+ | Hourly, 131k rows. |
| `ethusd_daily_bitstamp` | Bitstamp v2 OHLC | `.../ohlc/ethusd/?step=86400` | 2017-08+ | ETH daily. |

## On-chain (blockchain.info)

| Chart | Endpoint | Span |
|-------|----------|------|
| `bi_hash-rate` | `https://api.blockchain.info/charts/hash-rate?timespan=all&format=json&sampled=false` | 2009-01+ |
| `bi_difficulty` | `.../charts/difficulty?sampled=false` | 2009-01+ |
| `bi_n-unique-addresses` | `.../charts/n-unique-addresses?sampled=false` | 2009-01+ |
| `bi_n-transactions` | `.../charts/n-transactions?sampled=false` | 2009-01+ |
| `bi_market-cap` | `.../charts/market-cap?sampled=false` | 2009-01+ |
| `bi_total-bitcoins` | `.../charts/total-bitcoins?sampled=false` | 2009-01+ |

> **CRITICAL:** always pass `&sampled=false`. The default is WEEKLY sampling
> (~25% of data) which silently skews MAs/backtests.

## Sentiment + crypto liquidity

| Chart | Source | Endpoint | Span | Notes |
|-------|--------|----------|------|-------|
| `fear_greed` | alternative.me | `https://api.alternative.me/fng/?limit=3000&format=json` | 2018-05+ | Daily Fear & Greed index. |
| `stablecoin_total_liquidity` | DefiLlama | `https://stablecoins.llama.fi/stablecoincharts/all` | 2017-11+ | Aggregate USDT+USDC+DAI etc. Per-coin IDs 404 - use the aggregate. |

## Macro risk assets (Yahoo Finance)

12 charts, one row per day, 15y range. **429s on bursts - space requests ~8s apart.**

| Chart | Symbol | Endpoint |
|-------|--------|----------|
| `dxy` | DX-Y.NYB | `https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?range=15y&interval=1d` |
| `us10y` | ^TNX | `.../chart/%5ETNX?...` |
| `us30y` | ^TYX | `.../chart/%5ETYX?...` |
| `us3m` | ^IRX | `.../chart/%5EIRX?...` |
| `vix` | ^VIX | `.../chart/%5EVIX?...` |
| `sp500` | ^GSPC | `.../chart/%5EGSPC?...` |
| `nasdaq` | ^IXIC | `.../chart/%5EIXIC?...` |
| `russell2000` | ^RUT | `.../chart/%5ERUT?...` |
| `gold` | GC=F | `.../chart/GC%3DF?...` |
| `silver` | SI=F | `.../chart/SI%3DF?...` |
| `wti` | CL=F | `.../chart/CL%3DF?...` |
| `copper` | HG=F | `.../chart/HG%3DF?...` |

## FX (ECB official)

| Chart | Endpoint | Span |
|-------|----------|------|
| `ecb_usd` (EURUSD) | `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml` | 1999+ |
| `ecb_jpy` (USDJPY) | same XML | 1999+ |
| `ecb_cny` (USDCNY) | same XML | 2005+ |

EURUSD is ~57.6% of DXY. XML: dated Cube elements, currency-rate cubes are their DIRECT children (skip grandchildren without `time`).

## FRED (macro backbone - requires FRED_API_KEY)

Free key at `fredaccount.stlouisfed.org/register`; API docs at
`fred.stlouisfed.org/docs/api/api_key.html`. Runs when `FRED_API_KEY` is set
(loaded from `.env` by `scripts/refresh.sh`).

| Chart | Series ID | Freq | Span | Notes |
|-------|-----------|------|------|-------|
| `fred_us_m2` | M2SL | Monthly | 1959+ | M2 money supply. |
| `fred_fed_balance_sheet` | WALCL | Weekly | 2002+ | Fed balance sheet. |
| `fred_fed_funds_eff` | DFF | Daily | 1954+ | Effective fed funds. |
| `fred_us2y` | DGS2 | Daily | 1976+ | 2y Treasury yield. |
| `fred_us10y_fred` | DGS10 | Daily | 1962+ | 10y yield (FRED; `us10y` is Yahoo). |
| `fred_us30y_fred` | DGS30 | Daily | 1977+ | 30y yield (FRED; `us30y` is Yahoo). |
| `fred_breakeven10y` | T10YIE | Daily | 2003+ | 10y breakeven inflation. |
| `fred_real_yield10y` | DFII10 | Daily | 2003+ | 10y real yield. |
| `fred_cpi` | CPIAUCSL | Monthly | 1947+ | CPI. |
| `fred_pce` | PCEPI | Monthly | 1959+ | PCE price index. |
| `fred_unemployment` | UNRATE | Monthly | 1948+ | Unemployment rate. |
| `fred_jobless_claims` | ICSA | Weekly | 1967+ | Initial jobless claims. |
| `fred_nonfarm_payrolls` | PAYEMS | Monthly | 1939+ | Nonfarm payrolls. |
| `fred_hy_spread` | BAMLH0A0HYM2 | Daily | 2023-08+ | HY credit spread. Only back to 2023 (series discontinued). |
| `fred_ig_spread` | BAMLC0A0CM | Daily | 2023-08+ | IG credit spread. Same 2023 floor. |
| `fred_rrp` | RRPONTSYD | Daily | 2003+ | Fed reverse-repo pool - the liquidity buffer that drains first (added 2026-09-24; USD billions as served). |
| `fred_tga` | WTREGEN | Weekly | 2002+ | Treasury General Account, weekly; the daily counterpart is `tga_daily` below (added 2026-09-24; USD millions as served). |

**Gotchas:** ISM series `NAPM`/`NAPMN` are discontinued - skip them (HTTP 400).
HY/IG only date back to 2023 - the window is bounded by that.

## On-chain flow + cycle (Glassnode MCP - FROZEN since 2026-10-01)

> **2026-10-01: the keyless MCP door closed** - the endpoint now returns
> `401 "Authentication required. Sign in with your Glassnode account, or supply an
> API key via the X-Api-Key header."` **2026-10-02: the paid route was ruled out
> (owner decision) - the charts stay FROZEN at their last data; do not propose paid
> plans or OAuth.** Without a key the builder skips the on-chain fetch entirely
> (charts keep their committed history); the layer resumes automatically only if a
> key is ever configured, and because a fetch only ever covers the last 30 days an
> outage gap heals only within 30 days while appends are running.

> **FLAP 2026-09-24 (resolved):** the endpoint returned HTTP 401 "requires an OAuth access
> token" for anonymous clients for about two hours mid-morning (~08:35-10:45 UTC), then
> recovered on its own (verified with live fetches; the same-day build merged normally).
> The wall that stayed is the 2026-10-01 one above.

The public MCP endpoint (`https://mcp.glassnode.com`, JSON-RPC over HTTP) exposes the
metric catalogue; each fetch returns **only the last 30 days**.

| Chart | Metric endpoint | What it shows |
|-------|-----------------|---------------|
| `gn_exchange_netflow_btc` | `/v1/metrics/transactions/transfers_volume_exchanges_net` | BTC/day net flow to exchanges. Signed: negative = coins leaving exchanges (accumulation), positive = coins moving in (sell-side pressure). |
| `gn_exchange_balance_btc` | `/v1/metrics/distribution/balance_exchanges` | Total BTC held on exchange addresses. |
| `gn_sopr` | `/v1/metrics/indicators/sopr` | Spent Output Profit Ratio. ~1.0 = break-even; sustained >1 = profit-taking, <1 = capitulation. |
| `gn_nupl` | `/v1/metrics/indicators/net_unrealized_profit_loss` | Net Unrealised P/L ratio. Cycle-position gauge (euphoria / belief / optimism / hope / capitulation). |
| `gn_supply_in_profit_pct` | `/v1/metrics/supply/profit_relative` | Share of supply in profit (0-1). |

**ETH twins** (same metric definitions, `a=ETH`, for the ETH engine - the BTC charts keep
their original names, twins are suffixed `_eth`): `gn_exchange_netflow_eth`,
`gn_exchange_balance_eth`, `gn_sopr_eth`, `gn_nupl_eth`, `gn_supply_in_profit_pct_eth`.
Shifted ranges in the audit reflect the different unit scale (ETH balance ~15.6M, BTC ~3.3M).

> **CRITICAL - rolling window, merge-only.** The server caps every response at 30 days, so a
> plain overwrite would truncate these charts to a month on every run. They are written by
> `merge_csv()`: keyed by date, new values win, sorted ascending. The committed CSV **is** the
> history - it grows one day at a time. Backfill beyond 30 days is impossible for free; missing
> more than a month creates a permanent gap.
>
> **Cloudflare:** the endpoint bot-challenges bare clients. A full browser header set
> (`sec-ch-ua*`, `sec-fetch-*`, `Origin`, `Referer`) gets HTTP 200; a plain UA gets 403
> "Just a moment". Headers live in `GN_HEADERS` in the builder.
>
> **Fail-soft:** a Glassnode outage prints WARN lines and leaves the files untouched - it does
> NOT go into `FAILED`, so a Cloudflare hiccup cannot degrade the whole weekly refresh.

**Point-in-time twins (added 2026-09-12).** Every chart above also exists as `*_pit`
(`gn_exchange_netflow_btc_pit`, `gn_sopr_pit`, `gn_exchange_netflow_eth_pit`, ...). PIT is
Glassnode's immutable "data as it was known at the time" variant; the live series above is a
current best estimate that is restated as address clustering improves. Why both are stored:
measured over the same 30 days, BTC daily netflow differed from its PIT twin on 30/30 days
(mean 232%, max 1,150%, including one sign flip, and the 7-day sum flipped sign: +4,904 live
vs -19,494 PIT), while ETH agreed to 0.2%. Reliability is per-metric-per-window, so the pair is
what makes a flow read checkable. Free keyless access serves PIT series too (verified).

Rule: **describe with the live series, test with PIT**, and only state a flow direction when
`strategies/onchain_confidence.py` reports CONFIRMED for that metric.

Fast append (used by the daily check, ~10s, does not touch the slow sources) -
prints SKIPPED and fetches nothing when no key is configured (2026-10-02: the
paid route was declined):

```bash
./.venv/bin/python strategies/build_macro_dataset.py --glassnode-only   # live + PIT twins
./.venv/bin/python strategies/onchain_confidence.py                     # live-vs-PIT gate
```

## Flow-semantics family + US spot ETF flows (added 2026-09-24)

Source-hunt batch 1: eleven more keyless metrics on the same MCP endpoint, same
rolling-30d merge, same live + `*_pit` twins, same gate.

| Chart | Metric endpoint | What it shows |
|-------|-----------------|---------------|
| `gn_hodler_npc_btc` / `_eth` | `/v1/metrics/indicators/hodler_net_position_change` | Long-term-holder net position change (coins/day, signed). Positive = LTH cohort adding. |
| `gn_net_realized_pl` / `_eth` | `/v1/metrics/indicators/net_realized_profit_loss` | Net realized P/L in USD/day (signed). Who is taking profit/loss at this price. |
| `gn_sopr_adjusted` | `/v1/metrics/indicators/sopr_adjusted` | SOPR adjusted for spent-output age - cleaner cycle read than raw SOPR. |
| `gn_sopr_155d` | `/v1/metrics/indicators/sopr_more_155` | SOPR restricted to coins older than 155d (>1 = old coins selling at profit). |
| `gn_whales_to_exchanges` | `/v1/metrics/transactions/transfers_volume_whales_to_exchanges_sum` | Whale -> exchange transfer volume (coins/day). Sell-side pressure precursor. |
| `gn_exchanges_to_whales` | `/v1/metrics/transactions/transfers_volume_exchanges_to_whales_sum` | Exchange -> whale withdrawal volume (coins/day). |
| `gn_reshuffling_ratio` | `/v1/metrics/distribution/exchange_reshuffling_ratio` | Exchange reshuffling ratio (0-1): exchange-to-exchange churn, not real flow. |
| `gn_etf_flows_net_btc` / `_eth` | `/v1/metrics/institutions/us_spot_etf_flows_net` | US spot ETF net flows. Stored AS SERVED - the vendor does not document units; verify scale before comparing with USD headlines. |
| `gn_binance_inflow_btc` / `gn_binance_outflow_btc` (+ `_eth` twins, + `_pit`) | `/v1/metrics/transactions/transfers_volume_to_exchanges_sum` / `..._from_exchanges_sum` with `e=binance` | Gross daily coin volume transferred INTO / OUT OF Binance-labelled addresses (non-negative; net = inflow - outflow). The all-exchange totals exist unfiltered (`e` omitted) - used for validation, not committed. Live + PIT twins fetched in the same session (2026-09-27). |

First gate run (2026-09-24): hodler NPC (BTC+ETH), net realized P/L (BTC+ETH), adjusted SOPR,
SOPR 155d, and ETF net flows (BTC+ETH) all CONFIRMED. `gn_whales_to_exchanges` UNSTABLE
(4.5% mean daily diff), `gn_reshuffling_ratio` UNSTABLE (4.4%), and `gn_exchanges_to_whales`
**CONTRADICTED** (18.3% mean daily diff) - exchange/whale classification is heavily restated,
so use the PIT twin for any claim on it. ETH twins exist only where the endpoint serves ETH
(no adjusted/155d/whale twins for ETH).

## Treasury FiscalData - daily TGA (added 2026-09-24)

Keyless: `api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance`.
Daily Treasury General Account balance - the daily counterpart of FRED's weekly `fred_tga`.
With `fred_rrp` it enables the net-liquidity read (**Fed BS - TGA - RRP**).

Three naming eras are stitched into one series (verified 2026-09-24): 2010-01..2021-09
"Federal Reserve Account" / 2021-10..2022-04 "Treasury General Account (TGA)" /
2022-04.. "Treasury General Account (TGA) Closing Balance". Quirk: in the modern rows
`close_today_bal` is null - the closing value sits in `open_today_bal` (verified against
the $957B figure). Values are USD millions, stored as served.

## Derivatives (Deribit + Binance public archive) - added 2026-09-24

Replaces the planned Glassnode derivatives batch (the public MCP went OAuth-only -
first flap 2026-09-24, permanent 2026-10-01). All keyless; these sources have no PIT twins.

| Chart | Source | What it shows |
|-------|--------|---------------|
| `dvol_btc` / `dvol_eth` | Deribit public API `get_volatility_index_data` | DVOL daily close (options-implied 30d vol index, points). Fetched+merged each run. No SOL twin - that index was discontinued 2022-11-25. |
| `bn_oi_btc` / `bn_oi_eth` / `bn_oi_sol` | Binance archive `data.binance.vision` daily metrics zips | USD-M perp open interest (coins), 23:45 UTC snapshot. Append-only: the builder fetches missing days (3-day overlap, max 60/run). |
| `bn_lsr_btc` / `bn_lsr_eth` / `bn_lsr_sol` | same | Top-trader long/short ratio (accounts). >1 = top traders net long. |
| `bn_taker_btc` / `bn_taker_eth` / `bn_taker_sol` | same | Taker buy/sell volume ratio. >1 = aggressive buying. |
| `bn_funding_btc` / `bn_funding_eth` / `bn_funding_sol` | Binance archive monthly fundingRate zips | Daily SUM of the 8h funding rates (fraction/day). ~1 month lag (monthly files only). |

Deep history: `strategies/backfill_derivatives.py` (one-time; metrics from 2020-09 BTC /
2021-12 ETH / 2021-12 SOL; funding from 2020-01; DVOL from launch). The builder appends recent days -
the committed CSVs are the history. Notes: `api.binance.com` is geo-blocked from this
machine but the `data.binance.vision` archive is NOT (different host); old metrics files
(2020) have a different granularity but the same columns. Source gaps (verified
2026-09-24): top-trader L/S has no values 2021-12-30 through mid-Dec 2022 (empty fields
in the archive); the taker ratio has none 2021-12-30 through early May 2022.

## Solana (added 2026-11-18)

Onboarding SOL as a third engine asset. Every series below was probed live on
2026-11-18; the span column is the REAL first row, not the vendor's claim.

| Chart | Source | Endpoint | Span | Notes |
|-------|--------|----------|------|-------|
| `solusd_daily_yahoo` | Yahoo Finance (CCC aggregate) | `.../chart/SOL-USD?range=10y&interval=1d` | 2020-04-10 -> | Longest daily SOL history that exists keyless (SOL spot opened April 2020). OHLC + USD volume. THE price series the SOL engine uses. |
| `solusd_daily_okx` | OKX v5 | `https://www.okx.com/api/v5/market/history-candles?instId=SOL-USDT&bar=1D` | 2020-09-29 -> | Venue print + real quote volume. Paginated with `after` (100 per call, newest first). Cross-check: must stay within 3 percent of Yahoo (audit enforces it). |
| `sol_tvl_defillama` | DefiLlama | `https://api.llama.fi/v2/historicalChainTvl/Solana` | 2021-03-17 -> | Chain TVL, daily. |
| `sol_stablecoins_defillama` | DefiLlama | `https://stablecoins.llama.fi/stablecoincharts/Solana` | 2021-09-10 -> | Stablecoin supply minted on Solana (peggedUSD circulating). QUARTERLY SNAPSHOTS until 2023-01, daily after: any change window before 2023 is not a 30-day read. The audit judges gaps from 2023 only. |
| `sol_dex_volume_defillama` | DefiLlama | `https://api.llama.fi/overview/dexs/solana?excludeTotalDataChart=false` | 2021-10-02 -> | Daily DEX volume (USD). First ~4 weeks are warmup junk ($3, $100, $42k) - do not read the level before 2021-11. |
| `sol_fees_defillama` | DefiLlama | `https://api.llama.fi/summary/fees/solana?dataType=dailyFees` + `?dataType=dailyRevenue` | 2021-01-17 -> | Two payloads merged into one chart: `fees_usd` (what users paid) and `revenue_usd` (the burned share). |
| `bn_oi_sol` / `bn_lsr_sol` / `bn_taker_sol` | Binance archive `data.binance.vision` daily metrics zips | `.../daily/metrics/SOLUSDT/SOLUSDT-metrics-YYYY-MM-DD.zip` | 2021-12-01 -> | SOL perp opened 2020-08-11 but the alt METRICS archive only starts 2021-12-01 (2021-11-30 returns 404). OI is in SOL coins; multiply by the close for USD. |
| `bn_funding_sol` | Binance archive monthly fundingRate zips | `.../monthly/fundingRate/SOLUSDT/SOLUSDT-fundingRate-YYYY-MM.zip` | 2021-01 -> | Daily SUM of the 8h rates (fraction/day), ~1 month lag. |
| `solbtc_daily_okx` | OKX v5 | `.../history-candles?instId=SOL-BTC&bar=1D` | 2020-09-29 -> | The actual TRADED cross (price + BTC volume), zero zero-volume days. The engine still computes SOL/BTC from aligned USD closes; this chart is the venue check (median basis last 30d is printed in the tape and sits near +0.5%). |
| `sol_mcap_cmc` | CoinMarketCap data-api (keyless, undocumented) | `https://api.coinmarketcap.com/data-api/v3/cryptocurrency/historical?id=5426&convertId=2781&interval=1d` | 2020-04-10 -> | Daily OHLC + volume + market cap + circulating supply. Market cap is 0 before 2020-06 (CMC did not track supply yet). |
| `cmc_total_mcap` | CoinMarketCap data-api | `.../data-api/v3/global-metrics/quotes/historical?convertId=2781&interval=1d` | 2020-04-10 -> | Total crypto market cap + BTC and ETH dominance. The denominator for SOL.D and a macro read in its own right. |
| `sol_dominance` | DERIVED | `sol_mcap_cmc / cmc_total_mcap * 100` | 2020-06-02 -> | SOL.D exactly as a charting platform shows it. Rebuilt from the two committed inputs every run, so it can never disagree with them. |
| `soleth_daily` | DERIVED | `solusd_daily_yahoo / ethusd_daily_bitstamp` closes | 2020-04-10 -> | The OKX SOL-ETH market is dead (flat price, zero volume since listing), so the ratio is computed, never fetched. |

**CoinMarketCap plumbing note (verified 2026-11-18).** CoinGecko cannot serve either input
keyless (the global market-cap chart is PRO-only, `market_chart` caps at 365 days), so the
SOL.D denominator comes from CMC's public data-api. It answers keyless but ONLY in chunks:
a single request covering the whole history silently returns a SAMPLED series (731 rows for
2,400 days). The fetcher therefore walks 350-day windows (~7 calls per series) and keys the
rows by date, because the chunk boundaries are inclusive on both ends and repeat a day.

**Funding-interval caveat (Solana, Nov 2022).** Binance moved SOLUSDT from 8-hour to
2-hour funding during 2022-11-09..11-19 and pinned it at the -2 percent per-print cap, so
`bn_funding_sol` daily SUMS over that week run to -17 to -24 percent per day: 12 prints at
the cap, not a data bug. BTC/ETH never changed interval. The chart clips the axis and labels
the episode; never read that spike as a normal funding print.

Rejected on the same probe: **Deribit SOL DVOL**. `get_volatility_index_data`
answers for currency=SOL, but the index only published 2022-05-04 through
2022-11-25 and then stops (any request starting after 2022-11 returns nothing).
A dead 206-row series is not a data gap to wait out - it was not committed. For
SOL volatility use realized vol (daily log returns, 30d annualised) or perp funding
as the crowding read.

Also not available keyless for Solana (probed 2026-11-18): active addresses /
transactions (Artemis, TokenTerminal paywalled), validator count and staking yield
(no free historical API), token unlocks (no free API).

Weekly history is NOT stored as a chart: `strategies/sol_macro_report.py` resamples
`solusd_daily_yahoo` to weeks that END on Sunday, so price keeps one source of truth.

## What is NOT covered (known gaps)

- Per-protocol usage (DAU/DAA, fees, revenue, txns) - paywalled: Artemis and
  TokenTerminal require paid API keys. Not fetched.
- Token unlock schedules - no free API.
- Binance klines are geo-blocked (HTTP 451) from this machine - not usable.
- Stooq.com is JS-challenge-blocked - not usable.

## Refreshing

```bash
bash scripts/refresh.sh          # fetch all 119 charts + engine + audit + on-chain gate
bash scripts/refresh.sh --check  # status only
```

Charts are overwritten in place; `manifest.json` + `data/macro_dataset/README.md`
are regenerated each build.
