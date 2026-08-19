# Macro + Crypto Master Dataset

Built: 2026-08-19T16:17:46.843853+00:00

| Chart | Rows | Span | Source |
|---|---|---|---|
| btcusd_daily_bitstamp | 5481 | 2011-08-18 00:00:00 -> 2026-08-19 00:00:00 | Bitstamp v2 ohlc |
| btcusd_hourly_bitstamp | 131525 | 2011-08-18 12:00:00 -> 2026-08-19 16:00:00 | Bitstamp v2 ohlc |
| ethusd_daily_bitstamp | 3291 | 2017-08-16 00:00:00 -> 2026-08-19 00:00:00 | Bitstamp v2 ohlc |
| bi_hash-rate | 6432 | 2009-01-03 00:00:00 -> 2026-08-16 00:00:00 | blockchain.info API |
| bi_difficulty | 6432 | 2009-01-03 00:00:00 -> 2026-08-16 00:00:00 | blockchain.info API |
| bi_n-unique-addresses | 6406 | 2009-01-03 00:00:00 -> 2026-08-16 00:00:00 | blockchain.info API |
| bi_n-transactions | 6418 | 2009-01-17 00:00:00 -> 2026-08-16 00:00:00 | blockchain.info API |
| bi_market-cap | 928836 | 2009-01-03 18:15:05 -> 2026-08-19 08:33:22 | blockchain.info API |
| bi_total-bitcoins | 928832 | 2009-01-03 18:15:05 -> 2026-08-19 08:33:22 | blockchain.info API |
| fear_greed | 3000 | 2026-08-19 -> 2018-06-02 | alternative.me |
| dxy | 3769 | 2011-08-19 -> 2026-08-19 | Yahoo Finance |
| us10y | 19 | 2026-07-23 -> 2026-08-19 | Yahoo Finance |
| us30y | 19 | 2026-07-23 -> 2026-08-19 | Yahoo Finance |
| us3m | 19 | 2026-07-23 -> 2026-08-19 | Yahoo Finance |
| vix | 3769 | 2011-08-19 -> 2026-08-19 | Yahoo Finance |
| sp500 | 3768 | 2011-08-19 -> 2026-08-19 | Yahoo Finance |
| nasdaq | 3768 | 2011-08-19 -> 2026-08-19 | Yahoo Finance |
| russell2000 | 3768 | 2011-08-19 -> 2026-08-19 | Yahoo Finance |
| gold | 3770 | 2011-08-19 -> 2026-08-19 | Yahoo Finance |
| silver | 3770 | 2011-08-19 -> 2026-08-19 | Yahoo Finance |
| wti | 3771 | 2011-08-19 -> 2026-08-19 | Yahoo Finance |
| copper | 3771 | 2011-08-19 -> 2026-08-19 | Yahoo Finance |
| ecb_usd | 7074 | 2026-08-19 -> 1999-01-04 | ECB eurofxref-hist |
| ecb_jpy | 7074 | 2026-08-19 -> 1999-01-04 | ECB eurofxref-hist |
| ecb_cny | 5475 | 2026-08-19 -> 2005-04-01 | ECB eurofxref-hist |
| fred_us_m2 | 810 | 1959-01-01 -> 2026-06-01 | FRED M2SL |
| fred_fed_balance_sheet | 1235 | 2002-12-18 -> 2026-08-12 | FRED WALCL |
| fred_fed_funds_eff | 26346 | 1954-07-01 -> 2026-08-17 | FRED DFF |
| fred_us2y | 12549 | 1976-06-01 -> 2026-08-17 | FRED DGS2 |
| fred_us10y_fred | 16141 | 1962-01-02 -> 2026-08-17 | FRED DGS10 |
| fred_us30y_fred | 12371 | 1977-02-15 -> 2026-08-17 | FRED DGS30 |
| fred_breakeven10y | 5911 | 2003-01-02 -> 2026-08-18 | FRED T10YIE |
| fred_real_yield10y | 5910 | 2003-01-02 -> 2026-08-17 | FRED DFII10 |
| fred_cpi | 954 | 1947-01-01 -> 2026-07-01 | FRED CPIAUCSL |
| fred_pce | 810 | 1959-01-01 -> 2026-06-01 | FRED PCEPI |
| fred_unemployment | 942 | 1948-01-01 -> 2026-07-01 | FRED UNRATE |
| fred_jobless_claims | 3110 | 1967-01-07 -> 2026-08-08 | FRED ICSA |
| fred_nonfarm_payrolls | 1051 | 1939-01-01 -> 2026-07-01 | FRED PAYEMS |
| fred_hy_spread | 786 | 2023-08-21 -> 2026-08-18 | FRED BAMLH0A0HYM2 |
| fred_ig_spread | 785 | 2023-08-21 -> 2026-08-18 | FRED BAMLC0A0CM |
| eth_tvl_defillama | 3249 | 2017-09-27 -> 2026-08-19 | DefiLlama historicalChainTvl/Ethereum |
| ethbtc_daily_bitstamp | 3291 | 2017-08-16 00:00:00 -> 2026-08-19 00:00:00 | Bitstamp v2 ohlc |

FRED series (17) added when FRED_API_KEY env is set.
Update cadence: re-run script; charts overwrite in place.