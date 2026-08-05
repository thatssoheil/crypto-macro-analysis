# Data Sources

Every series in `data/macro_dataset/` (40 charts) and where it comes from.
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

**Gotchas:** ISM series `NAPM`/`NAPMN` are discontinued - skip them (HTTP 400).
HY/IG only date back to 2023 - the window is bounded by that.

## What is NOT covered (known gaps)

- Per-protocol usage (DAU/DAA, fees, revenue, txns) - paywalled: Artemis and
  TokenTerminal require paid API keys. Not fetched.
- Token unlock schedules - no free API.
- Binance klines are geo-blocked (HTTP 451) from this machine - not usable.
- Stooq.com is JS-challenge-blocked - not usable.

## Refreshing

```bash
bash scripts/refresh.sh          # fetch all 40 charts + re-run engine + audit
bash scripts/refresh.sh --check  # status only
```

Charts are overwritten in place; `manifest.json` + `data/macro_dataset/README.md`
are regenerated each build.
