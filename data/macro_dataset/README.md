# Macro + Crypto Master Dataset

Built: 2026-09-11T00:36:07.153554+00:00

| Chart | Rows | Span | Source |
|---|---|---|---|
| btcusd_daily_bitstamp | 5504 | 2011-08-18 00:00:00 -> 2026-09-11 00:00:00 | Bitstamp v2 ohlc |
| btcusd_hourly_bitstamp | 132061 | 2011-08-18 12:00:00 -> 2026-09-11 00:00:00 | Bitstamp v2 ohlc |
| ethusd_daily_bitstamp | 3314 | 2017-08-16 00:00:00 -> 2026-09-11 00:00:00 | Bitstamp v2 ohlc |
| bi_hash-rate | 6449 | 2009-01-03 00:00:00 -> 2026-09-09 00:00:00 | blockchain.info API |
| bi_difficulty | 6449 | 2009-01-03 00:00:00 -> 2026-09-09 00:00:00 | blockchain.info API |
| bi_n-unique-addresses | 6423 | 2009-01-03 00:00:00 -> 2026-09-09 00:00:00 | blockchain.info API |
| bi_n-transactions | 6435 | 2009-01-17 00:00:00 -> 2026-09-09 00:00:00 | blockchain.info API |
| bi_market-cap | 931085 | 2009-01-03 18:15:05 -> 2026-09-10 08:28:28 | blockchain.info API |
| bi_total-bitcoins | 931081 | 2009-01-03 18:15:05 -> 2026-09-10 08:28:28 | blockchain.info API |
| fear_greed | 3000 | 2026-09-11 -> 2018-06-25 | alternative.me |
| dxy | 3772 | 2011-09-12 -> 2026-09-11 | Yahoo Finance |
| us10y | 3770 | 2011-09-12 -> 2026-09-10 | Yahoo Finance |
| us30y | 3770 | 2011-09-12 -> 2026-09-10 | Yahoo Finance |
| us3m | 3770 | 2011-09-12 -> 2026-09-10 | Yahoo Finance |
| vix | 3773 | 2011-09-12 -> 2026-09-10 | Yahoo Finance |
| sp500 | 3771 | 2011-09-12 -> 2026-09-10 | Yahoo Finance |
| nasdaq | 3771 | 2011-09-12 -> 2026-09-10 | Yahoo Finance |
| russell2000 | 3771 | 2011-09-12 -> 2026-09-10 | Yahoo Finance |
| gold | 3770 | 2011-09-12 -> 2026-09-11 | Yahoo Finance |
| silver | 3770 | 2011-09-12 -> 2026-09-11 | Yahoo Finance |
| wti | 3771 | 2011-09-12 -> 2026-09-11 | Yahoo Finance |
| copper | 3771 | 2011-09-12 -> 2026-09-11 | Yahoo Finance |
| ecb_usd | 7090 | 2026-09-10 -> 1999-01-04 | ECB eurofxref-hist |
| ecb_jpy | 7090 | 2026-09-10 -> 1999-01-04 | ECB eurofxref-hist |
| ecb_cny | 5491 | 2026-09-10 -> 2005-04-01 | ECB eurofxref-hist |
| fred_us_m2 | 811 | 1959-01-01 -> 2026-07-01 | FRED M2SL |
| fred_fed_balance_sheet | 1239 | 2002-12-18 -> 2026-09-09 | FRED WALCL |
| fred_fed_funds_eff | 26369 | 1954-07-01 -> 2026-09-09 | FRED DFF |
| fred_us2y | 12565 | 1976-06-01 -> 2026-09-09 | FRED DGS2 |
| fred_us10y_fred | 16157 | 1962-01-02 -> 2026-09-09 | FRED DGS10 |
| fred_us30y_fred | 12387 | 1977-02-15 -> 2026-09-09 | FRED DGS30 |
| fred_breakeven10y | 5927 | 2003-01-02 -> 2026-09-10 | FRED T10YIE |
| fred_real_yield10y | 5926 | 2003-01-02 -> 2026-09-09 | FRED DFII10 |
| fred_cpi | 954 | 1947-01-01 -> 2026-07-01 | FRED CPIAUCSL |
| fred_pce | 811 | 1959-01-01 -> 2026-07-01 | FRED PCEPI |
| fred_unemployment | 943 | 1948-01-01 -> 2026-08-01 | FRED UNRATE |
| fred_jobless_claims | 3114 | 1967-01-07 -> 2026-09-05 | FRED ICSA |
| fred_nonfarm_payrolls | 1052 | 1939-01-01 -> 2026-08-01 | FRED PAYEMS |
| fred_hy_spread | 787 | 2023-09-11 -> 2026-09-09 | FRED BAMLH0A0HYM2 |
| fred_ig_spread | 786 | 2023-09-11 -> 2026-09-09 | FRED BAMLC0A0CM |
| eth_tvl_defillama | 3271 | 2017-09-27 -> 2026-09-10 | DefiLlama historicalChainTvl/Ethereum |
| ethbtc_daily_bitstamp | 3314 | 2017-08-16 00:00:00 -> 2026-09-11 00:00:00 | Bitstamp v2 ohlc |
| stablecoin_total_liquidity | 3208 | 2017-11-29 -> 2026-09-10 | DefiLlama stablecoincharts/all |

FRED series (17) added when FRED_API_KEY env is set.
Update cadence: re-run script; charts overwrite in place.