# Macro + Crypto Master Dataset

Built: 2026-09-02T11:21:04.350545+00:00

| Chart | Rows | Span | Source |
|---|---|---|---|
| btcusd_daily_bitstamp | 5495 | 2011-08-18 00:00:00 -> 2026-09-02 00:00:00 | Bitstamp v2 ohlc |
| btcusd_hourly_bitstamp | 131856 | 2011-08-18 12:00:00 -> 2026-09-02 11:00:00 | Bitstamp v2 ohlc |
| ethusd_daily_bitstamp | 3305 | 2017-08-16 00:00:00 -> 2026-09-02 00:00:00 | Bitstamp v2 ohlc |
| bi_hash-rate | 6441 | 2009-01-03 00:00:00 -> 2026-09-01 00:00:00 | blockchain.info API |
| bi_difficulty | 6441 | 2009-01-03 00:00:00 -> 2026-09-01 00:00:00 | blockchain.info API |
| bi_n-unique-addresses | 6415 | 2009-01-03 00:00:00 -> 2026-09-01 00:00:00 | blockchain.info API |
| bi_n-transactions | 6427 | 2009-01-17 00:00:00 -> 2026-09-01 00:00:00 | blockchain.info API |
| bi_market-cap | 930239 | 2009-01-03 18:15:05 -> 2026-09-02 07:56:04 | blockchain.info API |
| bi_total-bitcoins | 930235 | 2009-01-03 18:15:05 -> 2026-09-02 07:56:04 | blockchain.info API |
| fear_greed | 3000 | 2026-09-02 -> 2018-06-16 | alternative.me |
| dxy | 3771 | 2011-09-02 -> 2026-09-02 | Yahoo Finance |
| us10y | 3769 | 2011-09-01 -> 2026-09-01 | Yahoo Finance |
| us30y | 3769 | 2011-09-01 -> 2026-09-01 | Yahoo Finance |
| us3m | 3769 | 2011-09-01 -> 2026-09-01 | Yahoo Finance |
| vix | 3771 | 2011-09-02 -> 2026-09-02 | Yahoo Finance |
| sp500 | 3769 | 2011-09-02 -> 2026-09-01 | Yahoo Finance |
| nasdaq | 3769 | 2011-09-02 -> 2026-09-01 | Yahoo Finance |
| russell2000 | 3769 | 2011-09-02 -> 2026-09-01 | Yahoo Finance |
| gold | 3770 | 2011-09-02 -> 2026-09-02 | Yahoo Finance |
| silver | 3770 | 2011-09-02 -> 2026-09-02 | Yahoo Finance |
| wti | 3771 | 2011-09-02 -> 2026-09-02 | Yahoo Finance |
| copper | 3771 | 2011-09-02 -> 2026-09-02 | Yahoo Finance |
| ecb_usd | 7083 | 2026-09-01 -> 1999-01-04 | ECB eurofxref-hist |
| ecb_jpy | 7083 | 2026-09-01 -> 1999-01-04 | ECB eurofxref-hist |
| ecb_cny | 5484 | 2026-09-01 -> 2005-04-01 | ECB eurofxref-hist |
| fred_us_m2 | 811 | 1959-01-01 -> 2026-07-01 | FRED M2SL |
| fred_fed_balance_sheet | 1237 | 2002-12-18 -> 2026-08-26 | FRED WALCL |
| fred_fed_funds_eff | 26360 | 1954-07-01 -> 2026-08-31 | FRED DFF |
| fred_us2y | 12559 | 1976-06-01 -> 2026-08-31 | FRED DGS2 |
| fred_us10y_fred | 16151 | 1962-01-02 -> 2026-08-31 | FRED DGS10 |
| fred_us30y_fred | 12381 | 1977-02-15 -> 2026-08-31 | FRED DGS30 |
| fred_breakeven10y | 5921 | 2003-01-02 -> 2026-09-01 | FRED T10YIE |
| fred_real_yield10y | 5920 | 2003-01-02 -> 2026-08-31 | FRED DFII10 |
| fred_cpi | 954 | 1947-01-01 -> 2026-07-01 | FRED CPIAUCSL |
| fred_pce | 811 | 1959-01-01 -> 2026-07-01 | FRED PCEPI |
| fred_unemployment | 942 | 1948-01-01 -> 2026-07-01 | FRED UNRATE |
| fred_jobless_claims | 3112 | 1967-01-07 -> 2026-08-22 | FRED ICSA |
| fred_nonfarm_payrolls | 1051 | 1939-01-01 -> 2026-07-01 | FRED PAYEMS |
| fred_hy_spread | 785 | 2023-09-04 -> 2026-08-31 | FRED BAMLH0A0HYM2 |
| fred_ig_spread | 784 | 2023-09-04 -> 2026-08-31 | FRED BAMLC0A0CM |
| eth_tvl_defillama | 3263 | 2017-09-27 -> 2026-09-02 | DefiLlama historicalChainTvl/Ethereum |
| ethbtc_daily_bitstamp | 3305 | 2017-08-16 00:00:00 -> 2026-09-02 00:00:00 | Bitstamp v2 ohlc |
| stablecoin_total_liquidity | 3200 | 2017-11-29 -> 2026-09-02 | DefiLlama stablecoincharts/all |

FRED series (17) added when FRED_API_KEY env is set.
Update cadence: re-run script; charts overwrite in place.