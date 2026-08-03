# Macro Regime Investing (formerly forex-bot)

Long-term investment research: macro-economics analysis + crypto (BTC) with phase-based
cashing (hold gems in risk-on, liquidate to cash on regime shift, rebuy the next leg).

> Old forex/MT5 trading path retired (2026-08). Its data is preserved under
> `data/forex_archive/` and its strategies under `strategies/` (not removed, not used).

## Stack
- Python 3.11+ (venv at `.venv`)
- pandas / numpy — analysis
- requests — API fetching

## Structure
```
macro-invest/                      (was forex-bot)
  strategies/macro_regime_v3.py    # multi-signal regime engine (primary)
  strategies/macro_regime.py       # v1 (F&G only, deprecated)
  strategies/macro_backtest_v2.py  # backtest: 200d-MA trend filter (+9,510% vs +641%)
  strategies/build_macro_dataset.py# fetch all 26 keyless charts
  data/macro_dataset/              # 26 charts, 71MB (see manifest.json)
  data/forex_archive/              # retired forex data, preserved (48MB)
  data/macro/                      # regime reports (latest.md, json)
```

## Setup

```bash
# 1. Secrets (never committed)
cp .env.example .env    # then fill in your keys

# 2. Build/refresh the dataset (keyless sources; FRED runs when FRED_API_KEY set)
python strategies/build_macro_dataset.py

# 3. Run the regime engine (no fetch, uses local data)
python strategies/macro_regime_v3.py
```

## Secrets

API keys live in `.env` (gitignored). `.env.example` shows the required names.
Never commit real keys.

## Dataset (data/macro_dataset/, 26 charts)
- BTCUSD daily + hourly (Bitstamp, 2011+), ETH daily
- On-chain (blockchain.info, 2009+): hash-rate, difficulty, addresses, txns, market-cap, supply
- Sentiment: Fear & Greed (2018+); stablecoin total liquidity (2017+)
- Macro: DXY, US 3m/10y/30y yields, VIX, SPX, Nasdaq, Russell, Gold, Silver, WTI, Copper (Yahoo, 15yr)
- FX: EURUSD/USDJPY/USDCNY (ECB official, 1999+)
- FRED (17 series, when key provided): M2, Fed balance sheet, rates, CPI, PCE, labor, ISM, credit spreads

## Regime engine (v3)
9 weighted signals in 4 causal groups: liquidity (curve, stablecoins, DXY), risk
appetite (VIX, SPX), crypto-internal (BTC vs 200d MA, F&G, hash), inflation (gold).
Output: score in -3..+3 -> HOLD/ACCUMULATE, HOLD, NEUTRAL, REDUCE, LIQUIDATE.

## Validation so far
- 200d-MA trend filter beat buy-and-hold on real daily data 2017-2026:
  +9,510% vs +641%, max DD -55% vs -77%. v1 F&G-only scoring failed; replaced.
- Data quality: every chart span-verified row-count-verified; Bitstamp `sampled=false`
  is true daily (default is weekly).

## Status / Todo
- [x] Master dataset built (26 charts, 71MB)
- [ ] FRED API key -> add 17 macro series (liquidity/inflation/credit backbone)
- [ ] Cron: weekly regime review auto-delivery
- [ ] Backtest v3 multi-signal vs 2017-2026
- [ ] Gem-basket layer: apply regime filter to alt basket
```