# AGENTS.md

Agent guide for the macro-invest repo. Read this before changing anything.
README.md has the user-facing docs; this file is the operational contract.

## What this project is

Long-term macro-regime investing research for BTC. A regime engine scores the
macro environment and decides HOLD crypto / CASH out / BUY the dip, using
phase-based cashing: hold in risk-on, move to cash on regime shift, rebuy the
next leg. Everything runs on a locally-owned dataset of 40 CSV charts
(`data/macro_dataset/`). The repo is public (github.com/thatssoheil/macro-invest).

## Golden rules (tested facts - do not re-litigate)

1. **Analysis window is 2017-2026 only.** Every fetched series must have data
   there (F&G starts 2018-05, stablecoin aggregate 2017-11, HY/IG spreads 2023-08).
   Pre-2017 BTC is too volatile for drawdown-protection tests.
2. **The 200d-MA trend filter on BTC daily IS the validated edge:**
   2017-2026 it did +9,510% vs buy-and-hold +641%, max DD -55% vs -77%
   (true daily data; the "+1,111%" figure from weekly sampling is the known artifact).
3. **The v4 multi-signal composite does NOT beat the 200d-MA filter**
   (2017-2026: +2,903% vs +2,773%, DD -65.9% vs -67.2%). Tested, A/B'd.
   5-day hysteresis improves it to +3,495% / DD -58.9%. Do NOT re-weight the
   engine signals without an A/B backtest proving the improvement.
4. **Every claim needs A/B evidence.** The owner demands a backtest with vs
   without any proposed change before accepting it.
5. **Secrets live in `.env` (gitignored).** Never commit `.env` or any real key.

## Repo map

| Path | Purpose |
|------|---------|
| `strategies/macro_regime_v3.py` | LIVE regime engine (v4 logic). 14 weighted signals in 4 causal groups, score -3..+3 -> HOLD/ACCUMULATE, HOLD, NEUTRAL, REDUCE, LIQUIDATE + phase label. Consumes local data only, NO fetch. Writes `data/macro/latest.md` + dated JSON. |
| `strategies/build_macro_dataset.py` | Fetches all 40 charts (keyless sources; FRED runs when `FRED_API_KEY` set). Slow network job - only re-run to refresh data. |
| `strategies/audit_dataset.py` | Data-integrity + signal-correctness audit. RUN BEFORE trusting any aggregation. Recomputes every v4 signal independently (12/12 pass on 2026-08-05). |
| `strategies/macro_backtest_v4.py` | Multi-signal composite backtest 2017-2026 (the primary analysis tool). |
| `strategies/macro_backtest_deep.py` | 200d-MA filter on full 2011-2026 history (deep-window edge). |
| `strategies/dd_protection_sweep.py` | Drawdown-breaker layer sweep (MA x DD-% breakers). |
| `strategies/fng_ab_test.py` | Fear & Greed A/B - proved F&G is a risk-trimmer, not a return-driver. |
| `strategies/lead_time_analysis.py` | Macro early-warning lead times (M2 YoY peaks ~8-11 months before tops; DXY 200MA reclaim leads). |
| `strategies/macro_regime.py` | v1 engine (F&G-only) - FAILED (whipsaw), kept for lineage. |
| `strategies/macro_backtest.py` | v1 backtest. |
| `strategies/macro_backtest_v2.py` | v2 backtest (200d-MA trend filter). |
| `strategies/build_btc_dataset.py` | Standalone BTC price builder (blockchain.info). |
| `scripts/self_update.sh` | Self-update runner: git pull + dataset refresh (if >7d stale) + regime engine + audit. Invoked by cron or manually. |
| `data/macro_dataset/` | 40 charts, one CSV per series + `manifest.json` (source/span/rows per chart) + auto-generated README. |
| `data/macro/` | Regime reports (`latest.md`, dated JSON) + backtest result JSONs. |

## Self-update (permission-gated)

The repo is designed to self-update on ANY system, but ONLY with user permission:

- **Manual:** `bash scripts/self_update.sh` (full refresh) or `--check` (status only)
- **Scheduled (this machine):** a weekly cron job runs `scripts/self_update.sh`
  every Monday 09:00 and reports the fresh verdict. It is `deliver: local`
  (output saved, not pushed anywhere) - the user opted into this.
- **The runner is safe by construction:** `git pull --ff-only` (never overwrites
  local changes, never merge-commits), dataset re-fetch only if `manifest.json`
  is missing or >7d old, engine + audit run read-only, and it exits 1 on any
  failure instead of forcing anything.
- **Any agent or system may run the runner to get a fresh verdict, but must not
  fetch, push, or modify the repo without explicit user instruction.**

## Commands

```bash
cd ~/projects/macro-invest
./.venv/bin/python strategies/macro_regime_v3.py       # engine -> latest.md + JSON
./.venv/bin/python strategies/audit_dataset.py         # 12/12 signal checks
./.venv/bin/python strategies/macro_backtest_v4.py     # composite backtest -> v4_composite_backtest.json
./.venv/bin/python strategies/macro_backtest_deep.py   # deep-history backtest
./.venv/bin/python strategies/build_macro_dataset.py   # refresh dataset (slow, network)
./.venv/bin/python strategies/dd_protection_sweep.py   # DD layer sweep
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
- **$10k start**; results in `data/macro/*.json`.
- Known results (2017-2026, $10k, daily closes) - a regression check:

| Strategy | Final | CAGR | MaxDD | Flips |
|---|---|---|---|---|
| v4 composite (score >= +0.5) | +2,903% | +42.6% | -65.9% | 239 |
| v4 + 5d hysteresis | +3,495% | +45.3% | -58.9% | 95 |
| 200d-MA filter | +2,773% | +41.9% | -67.2% | 69 |
| buy-and-hold | +6,181% | +54.0% | -83.4% | 0 |

- 200d-MA filter, deep history (2011-2026): +820,555% vs BH +574,821%,
  DD -80.9% vs -84.9% (see `deep_history_backtest.json`).
- 50d-MA OR DD-20% breaker (2017-2026): max DD **-19.8%** - the best
  drawdown-protection layer stack (see `dd_protection_sweep_2017.json`).

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

- Latest regime read 2026-08-05: score **+1.4 -> HOLD**, PHASE 1 risk-on.
  BTC $64.1k still below its 200d MA $70.8k - "fuel present, ignition not yet."
- Open items: weekly regime-review cron; gem-basket layer (regime filter on an
  alt basket); per-protocol usage data (DAU/fees) is paywalled (Artemis/TokenTerminal).
