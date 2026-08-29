# Macro + Crypto Master Dataset

Built: 2026-08-29T00:28:52.059143+00:00

| Chart | Rows | Span | Source |
|---|---|---|---|
| btcusd_daily_bitstamp | 5491 | 2011-08-18 00:00:00 -> 2026-08-29 00:00:00 | Bitstamp v2 ohlc |
| btcusd_hourly_bitstamp | 131749 | 2011-08-18 12:00:00 -> 2026-08-29 00:00:00 | Bitstamp v2 ohlc |
| ethusd_daily_bitstamp | 3301 | 2017-08-16 00:00:00 -> 2026-08-29 00:00:00 | Bitstamp v2 ohlc |
| bi_hash-rate | 6436 | 2009-01-03 00:00:00 -> 2026-08-27 00:00:00 | blockchain.info API |
| bi_difficulty | 6436 | 2009-01-03 00:00:00 -> 2026-08-27 00:00:00 | blockchain.info API |
| bi_n-unique-addresses | 6410 | 2009-01-03 00:00:00 -> 2026-08-27 00:00:00 | blockchain.info API |
| bi_n-transactions | 6422 | 2009-01-17 00:00:00 -> 2026-08-27 00:00:00 | blockchain.info API |
| bi_market-cap | 929726 | 2009-01-03 18:15:05 -> 2026-08-28 08:25:07 | blockchain.info API |
| bi_total-bitcoins | 929722 | 2009-01-03 18:15:05 -> 2026-08-28 08:25:07 | blockchain.info API |
| fear_greed | 3000 | 2026-08-29 -> 2018-06-12 | alternative.me |
| dxy | 3773 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| us10y | 3771 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| us30y | 3771 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| us3m | 3771 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| vix | 3773 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| sp500 | 3772 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| nasdaq | 3772 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| russell2000 | 3772 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| gold | 3771 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| silver | 3771 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| wti | 3772 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| copper | 3772 | 2011-08-29 -> 2026-08-28 | Yahoo Finance |
| ecb_usd | 7081 | 2026-08-28 -> 1999-01-04 | ECB eurofxref-hist |
| ecb_jpy | 7081 | 2026-08-28 -> 1999-01-04 | ECB eurofxref-hist |
| ecb_cny | 5482 | 2026-08-28 -> 2005-04-01 | ECB eurofxref-hist |
| fred_us_m2 | 811 | 1959-01-01 -> 2026-07-01 | FRED M2SL |
| fred_fed_balance_sheet | 1237 | 2002-12-18 -> 2026-08-26 | FRED WALCL |
| fred_fed_funds_eff | 26356 | 1954-07-01 -> 2026-08-27 | FRED DFF |
| fred_us2y | 12557 | 1976-06-01 -> 2026-08-27 | FRED DGS2 |
| fred_us10y_fred | 16149 | 1962-01-02 -> 2026-08-27 | FRED DGS10 |
| fred_us30y_fred | 12379 | 1977-02-15 -> 2026-08-27 | FRED DGS30 |
| fred_breakeven10y | 5919 | 2003-01-02 -> 2026-08-28 | FRED T10YIE |
| fred_real_yield10y | 5918 | 2003-01-02 -> 2026-08-27 | FRED DFII10 |
| fred_cpi | 954 | 1947-01-01 -> 2026-07-01 | FRED CPIAUCSL |
| fred_pce | 811 | 1959-01-01 -> 2026-07-01 | FRED PCEPI |
| fred_unemployment | 942 | 1948-01-01 -> 2026-07-01 | FRED UNRATE |
| fred_jobless_claims | 3112 | 1967-01-07 -> 2026-08-22 | FRED ICSA |
| fred_nonfarm_payrolls | 1051 | 1939-01-01 -> 2026-07-01 | FRED PAYEMS |
| fred_hy_spread | 787 | 2023-08-29 -> 2026-08-27 | FRED BAMLH0A0HYM2 |
| fred_ig_spread | 786 | 2023-08-29 -> 2026-08-27 | FRED BAMLC0A0CM |
| eth_tvl_defillama | 3258 | 2017-09-27 -> 2026-08-28 | DefiLlama historicalChainTvl/Ethereum |
| ethbtc_daily_bitstamp | 3301 | 2017-08-16 00:00:00 -> 2026-08-29 00:00:00 | Bitstamp v2 ohlc |
| stablecoin_total_liquidity | 3195 | 2017-11-29 -> 2026-08-28 | DefiLlama stablecoincharts/all |

FRED series (17) added when FRED_API_KEY env is set.
Update cadence: re-run script; charts overwrite in place.