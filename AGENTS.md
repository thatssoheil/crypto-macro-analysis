# AGENTS.md

Agent guide for the btc-macro-analysis repo. Read this before changing anything.
README.md has the user-facing docs; this file is the operational contract.

## What this project is

Long-term macro-regime investing research for BTC. A regime engine scores the
macro environment and decides HOLD crypto / CASH out / BUY the dip, using
phase-based cashing: hold in risk-on, move to cash on regime shift, rebuy the
next leg. Everything runs on a locally-owned dataset of 40 CSV charts
(`data/macro_dataset/`). The repo is public (github.com/thatssoheil/btc-macro-analysis).

## Golden rules (tested facts - do not re-litigate)

1. **Analysis window is 2017-2026 only.** Every fetched series must have data
   there (F&G starts 2018-05, stablecoin aggregate 2017-11, HY/IG spreads 2023-08).
   Pre-2017 BTC is too volatile for drawdown-protection tests.
2. **The 200d-MA trend filter on BTC daily IS the validated edge:** it beats
   buy-and-hold across every window tested (2011-2026 and 2017-2026) with a
   much lower max drawdown. Reproduce: `strategies/macro_backtest_deep.py`.
   (The "+1,111%" figure from weekly sampling is the known artifact - always
   use true daily data, `sampled=false`.)
3. **The v4 multi-signal composite does NOT beat the 200d-MA filter** as an
   execution switch (tested, A/B'd: it whipsaws - hundreds of flips vs ~70 for
   the MA). Hysteresis trims the drawdown but it stays a risk-trimmer, not a
   return-driver. Use the score as CONTEXT, not the switch. Do NOT re-weight
   the engine signals without an A/B backtest proving the improvement.
   Reproduce: `strategies/macro_backtest_v4.py`.
4. **Every claim needs A/B evidence.** The owner demands a backtest with vs
   without any proposed change before accepting it.
5. **Secrets live in `.env` (gitignored).** Never commit `.env` or any real key.
   A fresh `git clone` deletes `.env` - restore `FRED_API_KEY` after cloning
   (recoverable from session history if lost).
6. **The repo is STATELESS: results are never saved, never read back.** Every
   script regenerates its output fresh from the committed dataset and prints
   to stdout. `data/macro/` is gitignored scratch. Docs never hardcode result
   numbers - they would go stale as data appends. Run the script for the
   current number.

## Repo map

| Path | Purpose |
|------|---------|
| `strategies/macro_regime_v3.py` | LIVE regime engine (v4 logic). 14 weighted signals in 4 causal groups, score -3..+3 -> HOLD/ACCUMULATE, HOLD, NEUTRAL, REDUCE, LIQUIDATE + phase label. Consumes local data only, NO fetch. Stateless: prints verdict to stdout, saves nothing. |
| `strategies/eth_macro_regime.py` | ETH live regime engine (full macro backbone + ETH 200d MA + ETH/BTC + DefiLlama TVL). |
| `strategies/eth_macro_backtest.py` | ETH regime backtest 2017-2026 (validates 50d/200d MA + dual filters on ETH). |
| `strategies/build_macro_dataset.py` | Fetches all 42 charts (keyless sources; FRED runs when `FRED_API_KEY` set). Slow network job - only re-run to refresh data. |
| `strategies/audit_dataset.py` | Data-integrity + signal-correctness audit. RUN BEFORE trusting any aggregation. Recomputes every v4 signal independently (12/12 pass on every run). |
| `strategies/macro_backtest_v4.py` | Multi-signal composite backtest 2017-2026 (the primary analysis tool). |
| `strategies/macro_backtest_deep.py` | 200d-MA filter on full 2011-2026 history (deep-window edge). |
| `strategies/dd_protection_sweep.py` | Drawdown-breaker layer sweep (MA x DD-% breakers). |
| `strategies/fng_ab_test.py` | Fear & Greed A/B - proved F&G is a risk-trimmer, not a return-driver. |
| `strategies/lead_time_analysis.py` | Macro early-warning lead times (M2 YoY peaks ~8-11 months before tops; DXY 200MA reclaim leads). |
| `strategies/macro_regime.py` | v1 engine (F&G-only) - FAILED (whipsaw), kept for lineage. |
| `strategies/macro_backtest.py` | v1 backtest. |
| `strategies/macro_backtest_v2.py` | v2 backtest (200d-MA trend filter). |
| `strategies/build_btc_dataset.py` | Standalone BTC price builder (blockchain.info). |
| `scripts/refresh.sh` | On-demand refresh runner: fetch latest data (charts append daily) + re-run engine + audit. Run when the user asks for an update. `--check` = status only. |
| `data/macro_dataset/` | 40 charts, one CSV per series + `manifest.json` (source/span/rows per chart) + auto-generated README. |
| `data/macro/` | Gitignored scratch. Results are never committed - every script regenerates fresh and prints to stdout. |

## Refresh (on-demand, fetch + aggregate)

The data sources append new observations every day globally (Bitstamp, FRED,
Yahoo, blockchain.info, alternative.me, DefiLlama, ECB). The repo is **aware**
of this: it can fetch whatever is new and re-aggregate at any time, on any
system. There is NO cron/schedule - refresh happens only when asked:

- **User asks for an update** (or an agent decides a fresh read is needed):
  `bash scripts/refresh.sh` -> fetch latest charts -> re-run regime engine ->
  re-run audit -> print verdict (stdout, nothing saved).
- **`bash scripts/refresh.sh --check`** -> status only (HEAD, last fetch,
  BTC data-through date). No saved verdict exists to report.
- **Scope:** `scripts/refresh.sh` only refreshes LOCAL data + recomputes the
  verdict. It does NOT git-pull, does NOT push, does NOT schedule anything,
  does NOT save results. `build_macro_dataset.py` fetches keyless sources
  everywhere; FRED series run when `FRED_API_KEY` is set. If the user asks
  for an update and the network is down, report the error - never fabricate
  or use stale data silently.

## Commands

```bash
cd ~/projects/btc-macro-analysis
./.venv/bin/python strategies/macro_regime_v3.py       # engine -> verdict to stdout
./.venv/bin/python strategies/audit_dataset.py         # signal checks (12/12 pass)
./.venv/bin/python strategies/macro_backtest_v4.py     # composite backtest -> stdout
./.venv/bin/python strategies/macro_backtest_deep.py   # deep-history backtest -> stdout
./.venv/bin/python strategies/build_macro_dataset.py   # refresh dataset (slow, network)
./.venv/bin/python strategies/dd_protection_sweep.py   # DD layer sweep -> stdout
```

- Use `./.venv/bin/python` directly. Do NOT `source .venv/bin/activate` from a
  shared shell - it can resolve to the wrong venv.
- There is no test suite. Non-trivial new logic leaves ONE runnable check
  (an assert-based self-check or a small script in /tmp).

## Engine internals (the exact math in macro_regime_v3.py)

14 signals, each +1 risk-on / -1 risk-off / 0 neutral, grouped by causality:

| Group (weight) | Signals (weights) |
|---|---|
| A. LIQUIDITY (2.0) | curve 10y-3m (2.0, +1 if >0), stablecoin 30d change (2.0, +1 if >+2% / -1 if <-2%), DXY vs 200d MA (1.5), M2 YoY (2.0, +1 if >4% / -1 if <1%), Fed balance sheet 60d change (1.5, +1 if >+1% / -1 if <-1%) |
| B. RISK APPETITE (1.5) | VIX (1.5, +1 if <20 / -1 if >30), SPX vs 200d MA (1.5), HY credit spread (1.5, +1 if <3.5% / -1 if >5.5%) |
| C. CRYPTO INTERNAL (2.0) | BTC vs 200d MA (2.0), Fear & Greed (1.0, +1 if <30 / -1 if >70), hashrate vs 60d MA (0.5) |
| D. INFLATION/REAL (1.0) | 10y real yield (1.0, +1 if <1.5% / -1 if >2.5%), CPI YoY (0.5, +1 if <3% / -1 if >5%), gold vs 200d MA (0.5) |

Score = `sum(signal * weight) / sum(available weights) * 3`, rounded to 1dp.
Series that haven't started yet (NaN) are EXCLUDED from both sums - this is the
engine's "available signals" rule; replicate it in any backtest.

Verdict bands: >= +1.5 HOLD/ACCUMULATE, >= +0.5 HOLD, <= -1.5 LIQUIDATE,
<= -0.5 REDUCE, else NEUTRAL. Phase: >= +0.5 = PHASE 1 (risk-on hold+accumulate),
<= -0.5 = PHASE 2 (risk-off cash), else TRANSITION.

## Backtest conventions (CRITICAL - all scripts follow these)

- **No lookahead**: position for day t is decided by the signal at day t-1
  (close-based signals applied to the NEXT day's return). The v4 backtest
  `.shift(1)`s the in-market series.
- **Cash earns 0%** (conservative, no yield).
- **Daily closes only**; no slippage/fees.
- **$10k start**; results print to stdout (stateless - nothing is saved).
- **No stored results.** Every backtest regenerates from the current dataset.
  Any claimed number must be reproduced by running the named script - never
  copy a figure from an old run into docs (it goes stale as data appends).
  Qualitative findings (which strategy beats which, DD ordering) are stable;
  exact percentages are not.
- Sanity anchors (qualitative, from the validated runs): the 200d-MA filter
  beats buy-and-hold in every window; the v4 composite whipsaws vs the MA;
  the 50d-OR-DD-20% breaker has the lowest max DD of the swept layers in the
  2017-2026 window. Regenerate the numbers with the scripts.

## Data pitfalls (learned the hard way)

- **blockchain.info default is WEEKLY sampling.** Always pass `&sampled=false`
  or MAs/backtests silently run on ~25% of the data.
- **Bitstamp `start` is a FROM-filter, not an end.** To walk full history page
  with `start = oldest_timestamp - step*1000`; without `start` you get only the
  most recent 1000 candles.
- F&G only exists 2018-05+; HY/IG spreads only 2023-08+; stablecoin aggregate
  only 2017-11+. Any backtest joining these is window-bound by them.
- Binance klines are geo-blocked (HTTP 451) from this machine; Stooq is
  JS-challenge-blocked. Not usable sources.
- CoinGecko `market_chart` history 429s/401s keyless - do not use for history;
  `global` and `/coins/{id}` (current snapshot) work keyless.
- FRED ISM series `NAPM`/`NAPMN` are discontinued - they fail, skip them.
- Yahoo Finance 429s on bursts - space requests ~8s apart with backoff.

## Simulation pitfalls

- **Equity-wipe bug**: in a cash day the equity update must be `* 1.0`, never
  `* 0` (that zeroes the account). A -100% trend-follow result is a math bug.
- `np.where()` returns an ndarray, not a Series - wrap as
  `pd.Series(np.where(...), index=df.index)` before `.reindex()`/`.fillna()`.
- numpy bools are not JSON-serializable - cast `bool(...)`/`float(...)` before `json.dump`.
- Define functions BEFORE building strategy lists; `(f := None)` in a list
  literal evaluates at list-build time and pollutes the entry.

## Conventions

- ASCII hyphens only in prose/docs (owner preference; no en/em dashes).
- Stdlib and native first; never add a dependency for a few lines.
- Fewest files, shortest working diff. Deletion over addition.
- One change per commit; clear commit messages. This is a main-only repo -
  direct push to `origin/main` is the owner's workflow.

## Current state (context for agents)

- **No stored verdict.** Run `bash scripts/refresh.sh` for the current read;
  the engine prints it to stdout. Qualitative context (2026-08): the macro
  layer reads risk-on (M2 expanding, Fed BS growing, HY tight, curve steep,
  VIX calm) while BTC still sits below its 200d MA - "fuel present, ignition
  not yet." The trend filter has been in cash since the 2025-11-03 cross below.
- Open items: gem-basket layer (regime filter on an
  alt basket); per-protocol usage data (DAU/fees) is paywalled (Artemis/TokenTerminal).
