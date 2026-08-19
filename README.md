# Macro Regime Investing

Long-term investment research: macro-economics analysis + crypto (BTC) with **phase-based
cashing** — hold in risk-on regimes, move to cash on regime shift, rebuy on the next leg up.

> **For agents/AI:** read [`AGENTS.md`](AGENTS.md) first - it has the golden rules,
> engine math, backtest conventions, and data pitfalls (operational contract).
> README.md is the user-facing overview.

**The core validated edge:** a 200-day moving-average trend filter on BTC daily
beats buy-and-hold over the 2017-2026 analysis window with a much lower max
drawdown (reproduce: `./.venv/bin/python strategies/macro_backtest_deep.py`).
A 50d-MA-or-DD-20% breaker caps the worst experienced drawdown around -20%
(reproduce: `./.venv/bin/python strategies/dd_protection_sweep.py`).

**Stateless by design:** the repo stores code + fetched data only. Every run
regenerates results fresh from the dataset and prints them to stdout - nothing
is saved, nothing reads back a previous result. Run any script to get the
current numbers; docs never hardcode them (they would go stale).

## What this repo gives you

- **A complete, locally-stored macro + crypto dataset** (42 charts, CSV, one file per series)
  covering money supply, rates, inflation, dollar, risk appetite, on-chain, and sentiment.
- **A regime engine** that scores the current macro environment into a
  **HOLD / CASH / BUY-the-dip** phase, using 14 weighted signals across 4 causal groups.
- **Backtest + audit scripts** proving (and checking) every claim with real data.

Current verdict: `bash scripts/refresh.sh` (fetches latest data, re-runs engine + audit).

## Quickstart

```bash
git clone https://github.com/thatssoheil/btc-macro-analysis
cd btc-macro-analysis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # optional: add your FRED_API_KEY (free at fred.stlouisfed.org)

# 1. Refresh the dataset (keyless sources; FRED runs when key set)
python strategies/build_macro_dataset.py

# 2. Read the current regime verdict (no network needed - uses local data)
python strategies/macro_regime_v3.py

# 3. Audit data integrity + signal correctness
python strategies/audit_dataset.py
```

All scripts print their results to stdout (stateless - nothing is saved).

## Refresh (on-demand, fetch + aggregate)

Data sources append new observations every day (Bitstamp, FRED, Yahoo,
blockchain.info, alternative.me, DefiLlama, ECB). The repo knows how to fetch
whatever is new and re-aggregate - just ask:

```bash
bash scripts/refresh.sh          # fetch latest data + re-run engine + audit
bash scripts/refresh.sh --check  # status only (HEAD, last fetch, BTC data through)
```

`refresh.sh` only touches local data and prints the verdict - it never git-pulls,
pushes, schedules, or saves results. Runs on any system with a venv.

## The dataset (data/macro_dataset/, 40 charts)

| Group | Series | Source | Span |
|-------|--------|--------|------|
| **Crypto price** | BTCUSD daily + hourly, ETHUSD daily | Bitstamp | 2011+ |
| **On-chain** | hash-rate, difficulty, active addresses, transactions, market-cap, total supply | blockchain.info | 2009+ |
| **Sentiment** | Fear & Greed index | alternative.me | 2018+ |
| **Crypto liquidity** | stablecoin total supply (aggregate USDT/USDC/DAI) | DefiLlama | 2017+ |
| **Dollar/FX** | DXY, EURUSD, USDJPY, USDCNY | Yahoo / ECB | 1999+ |
| **Rates & curve** | 3m, 2y, 10y, 30y yields, 10y real yield, breakeven | Yahoo / FRED | 1962+ |
| **Money & Fed** | M2 money supply, Fed balance sheet, effective fed funds | FRED | 1954+ |
| **Inflation** | CPI, PCE | FRED | 1947+ |
| **Labor** | unemployment, jobless claims, nonfarm payrolls | FRED | 1939+ |
| **Risk appetite** | VIX, S&P 500, Nasdaq, Russell 2000, HY/IG credit spreads | Yahoo / FRED | 2011+ |
| **Commodities** | gold, silver, WTI crude, copper | Yahoo | 2011+ |

Every file: `timestamp,value` (or OHLCV for price charts), one row per day,
source + span + row-count recorded in `manifest.json`.

> **Every data source, endpoint, and known gap is documented in
> [`SOURCES.md`](SOURCES.md).** Read it before adding a new chart.

## The regime engine (strategies/macro_regime_v3.py)

14 weighted signals, each voting risk-on (+1) / risk-off (-1) / neutral (0):

| Signal | Weight | Signal | Weight |
|--------|--------|--------|--------|
| BTC vs 200d MA | 2.0 | DXY trend | 1.5 |
| M2 YoY growth | 2.0 | VIX regime | 1.5 |
| Yield curve 10y-3m | 2.0 | SPX vs 200d MA | 1.5 |
| Stablecoin 30d flow | 2.0 | HY credit spread | 1.5 |
| Fed balance sheet | 1.5 | Fear & Greed | 1.0 |
| 10y real yield | 1.0 | CPI YoY | 0.5 |
| Hash rate trend | 0.5 | Gold trend | 0.5 |

Score -3..+3 → **Phase 1 HOLD/ACCUMULATE** (≥+0.5), **Transition**, or
**Phase 2 CASH** (≤-0.5). Prints the full report to stdout (stateless).

## Validation (reproduce with the scripts - no stored numbers)

| Finding | Reproduce with |
|------|--------|
| 200d-MA trend filter beats buy-and-hold (2017-26, lower DD) | `strategies/macro_backtest_deep.py` |
| v4 composite does NOT beat the MA filter; hysteresis trims DD | `strategies/macro_backtest_v4.py` |
| 50d OR DD-20% breaker = best drawdown protection | `strategies/dd_protection_sweep.py` |
| Fear & Greed is a risk-trimmer, not a return-driver | `strategies/fng_ab_test.py` |
| Macro leads tops by ~8-11 months (M2/DXY warning cluster) | `strategies/lead_time_analysis.py` |
| Data integrity + signal-correctness audit | `strategies/audit_dataset.py` |

> Window note: 2017-2026 is the analysis window — every fetched series has data there
> (F&G starts 2018-05, stablecoins 2017, HY spreads 2023). Earlier BTC (2011-2016) is
> too volatile for reliable drawdown protection tests.

## Repository layout

```
btc-macro-analysis/
  strategies/
    build_macro_dataset.py   # fetch all 42 charts (keyless + FRED when key set)
    macro_regime_v3.py       # the live BTC regime engine (14 signals, 4 causal groups)
    eth_macro_regime.py      # live ETH regime engine (macro backbone + ETH internals)
    eth_macro_backtest.py    # ETH backtest (2017-2026)
    audit_dataset.py         # data-integrity + signal-correctness audit
    macro_backtest_v4.py     # multi-signal composite backtest (2017-2026)
    macro_backtest_deep.py   # 200d-MA filter, deep history (2011-2026)
    dd_protection_sweep.py   # drawdown-breaker layer sweep
    fng_ab_test.py           # Fear & Greed A/B
    lead_time_analysis.py    # macro early-warning lead-time study
    macro_regime.py          # v1 engine (F&G-only, deprecated - failed)
    macro_backtest.py        # v1 backtest
    macro_backtest_v2.py     # v2 backtest (200d-MA filter)
    build_btc_dataset.py     # standalone BTC price builder (blockchain.info)
  data/
    macro_dataset/           # 42 charts, one CSV per series (+ manifest.json, README.md)
  scripts/
    refresh.sh               # on-demand fetch + engine + audit (stateless)
  .env.example               # copy to .env and fill in FRED_API_KEY
  requirements.txt
```

All results print to stdout; `data/macro/` is gitignored scratch (never committed).

## Secrets

API keys go in `.env` (gitignored). `.env.example` lists the names.
`FRED_API_KEY` is optional — keyless sources cover everything except the 15 FRED series.
Note: a fresh `git clone` deletes `.env` (gitignored) - restore the key after cloning.

## Status / Todo

- [x] Dataset (40 charts) + manifest + audit
- [x] Regime engine v4 (14 signals, FRED backbone)
- [x] DD-protection sweep (breaker layers)
- [x] Multi-signal backtest vs 2017-2026 (v4 composite: does NOT beat MA filter; hysteresis helps DD)
- [x] On-demand refresh (`scripts/refresh.sh` - fetch latest + re-aggregate when asked)
- [x] Stateless results (stdout-only; nothing saved, nothing read back)
- [ ] Gem-basket layer: regime filter applied to an altcoin basket

## License

MIT - see [LICENSE](LICENSE). Use, modify, and sell freely; keep the
attribution. No warranty - this is research, not financial advice.
