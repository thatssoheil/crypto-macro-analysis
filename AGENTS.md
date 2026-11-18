# AGENTS.md

Agent guide for the crypto-macro-analysis repo. Read this before changing anything.
README.md has the user-facing docs; this file is the operational contract.

## What this project is

Long-term macro-regime investing research for BTC, ETH & SOL. A regime engine scores the
macro environment and decides HOLD crypto / CASH out / BUY the dip, using
phase-based cashing: hold in risk-on, move to cash on regime shift, rebuy the
next leg. Everything runs on a locally-owned dataset of 42 CSV charts
(`data/macro_dataset/`). The repo is public (github.com/thatssoheil/crypto-macro-analysis).

## Golden rules (tested facts - do not re-litigate)

1. **Analysis window is 2017-2026 only.** Every fetched series must have data
   there (F&G starts 2018-05, stablecoin aggregate 2017-11, HY/IG spreads 2023-08).
   Pre-2017 BTC is too volatile for drawdown-protection tests.
2. **The 200d-MA trend filter is a DRAWDOWN reducer, not a return edge.** Rewritten
   2026-11-04 after an adversarial audit found that `macro_backtest_deep.py` and
   `macro_backtest_v2.py` decided the position on the same close whose return they then
   earned (same-day lookahead). With the lag fixed: 2017-2026 the filter ends at $730,547
   versus $777,806 buy-and-hold (-67.2% max drawdown versus -83.4%), and the 2019-2021
   window it LOSES ($44,038 versus $120,871). It never "beats buy-and-hold in every
   window". Reproduce: `strategies/macro_backtest_deep.py` (now lagged).
3. **Neither the composite nor the filter is a proven return engine.** Fixed 2026-11-04:
   the composite replay had three growth signals (stablecoins, M2, Fed balance sheet)
   encoded backwards, inverting 5.5 of 19 weight. With that repaired and the 200-day
   baseline warmed on full history, 2017-2026 gives: composite score>0 $1,165,574
   (-69.5% drawdown, 110 flips), composite score>=+0.5 $486,999, 200-day filter $730,547,
   buy-and-hold $777,806. The score>0 arm now leads, but its threshold was not
   pre-declared - treat it as a hypothesis requiring an out-of-sample A/B, not a finding.
   Use the score as CONTEXT, never as an order. Do NOT re-weight signals without an A/B.
   Reproduce: `strategies/macro_backtest_v4.py`.
3b. **The moving-average LENGTH is not stable across cycles - do not tune it.** The
   2017-2026 sweep prefers 50-150 days over 200, which looks like an improvement. A
   pre-declared holdout on 2011-2016 (a window the sweep never saw) FAILS that choice:
   MA100 $455,665 versus $886,514 buy-and-hold, 1 of 4 criteria met, while MA200 at
   $914,530 was the only length that did not lose money there. Conclusion: keep 200 days
   as the drawdown reducer and expect no return from it; any length chosen on one window
   is a curve fit until it survives a holdout. Reproduce:
   `strategies/ma_length_holdout.py` (criteria frozen in its docstring before the run).

3c. **There is no profit-zone floor, and position size is a linear trade, not a fix.**
   Measured on both windows: capping giveback at about -50% costs roughly 80% of
   buy-and-hold wealth; capping it at -30% costs about 95%. The 200-day switch is the only
   nearly-free point on that frontier (-83% to -67% drawdown for 0.94x/1.03x wealth).
   Reproduce: `strategies/ma_drawdown_holdout.py` and `strategies/exposure_holdout.py`.
   Never promise a low-drawdown rule to the owner without quoting the wealth it costs.

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

7. **The macro composite does not transfer to SOL as built (tested 2026-11-18).** On SOL
   2023-01 -> 2026-11 the composite (score >= 0) returned -29% while holding returned
   +649%; it whipsawed (74-88 flips) and sat in cash through the recovery. The 200d and
   50d MA filters also UNDERPERFORM hold in that window (0.41x and 0.52x). Every arm that
   looks spectacular on the full 2020-2026 window is monetising 2021 once. Reproduce:
   `strategies/sol_macro_backtest.py` (it prints the per-window table for exactly this
   reason). Do not quote a SOL overlay multiple without its RECOVERY-window row.

## Repo map

| Path | Purpose |
|------|---------|
| `strategies/macro_regime_v3.py` | LIVE regime engine (v4 logic). 14 weighted signals in 4 causal groups, score -3..+3 -> HOLD/ACCUMULATE, HOLD, NEUTRAL, REDUCE, LIQUIDATE + phase label. Consumes local data only, NO fetch. Stateless: prints verdict to stdout, saves nothing. |
| `strategies/eth_macro_regime.py` | ETH live regime engine (full macro backbone + ETH 200d MA + ETH/BTC + DefiLlama TVL). |
| `strategies/eth_macro_backtest.py` | ETH regime backtest 2017-2026 (validates 50d/200d MA + dual filters on ETH). |
| `strategies/sol_macro_regime.py` | SOL live regime engine (macro backbone + SOL 200d MA + SOL/BTC + Solana TVL, stablecoin supply, DEX activity). |
| `strategies/sol_macro_report.py` | SOL tape as stdout: daily + weekly history, volume, ratios, chain economics, derivatives, macro backdrop, switch levels. |
| `strategies/sol_macro_backtest.py` | SOL backtest 2020-2026 (hold vs MA filters vs composite) plus the A/B for the two experimental SOL-native signals. |
| `strategies/asset_tape.py` | THE tape for any onboarded asset (`--asset SOL|ZEC`): daily + weekly history, volume, ratios, dominance, chain or supply economics, derivatives, macro backdrop, switch levels. `sol_macro_report.py` is a shim onto it. ZEC has no regime engine yet - the tape is its data layer. |
| `research/drawdown_state_study.py` | Forward returns conditioned on drawdown state (`--asset SOL|ZEC`); the honest way to answer "should I accumulate here". |
| `strategies/btc_eth_rotation.py` | BTC<->ETH rotation engine (validated DUALM50 rule: ETH/BTC 50d MA + ETH 200d MA + VIX/SPX macro gate). Prints the live verdict, the A/B backtest with costs, and the blunt caveats. |
| `strategies/build_macro_dataset.py` | Fetches all charts (keyless sources; FRED runs when `FRED_API_KEY` set). Slow network job - only re-run to refresh data. `--glassnode-only` is the fast path (on-chain append only, ~10s). |
| `strategies/audit_dataset.py` | Data-integrity + signal-correctness audit. RUN BEFORE trusting any aggregation. Recomputes every v4 signal independently (all checks pass on every run). |
| `strategies/macro_backtest_v4.py` | Multi-signal composite backtest 2017-2026 (the primary analysis tool). |
| `strategies/macro_backtest_deep.py` | 200d-MA filter on full 2011-2026 history (deep-window edge). |
| `strategies/dd_protection_sweep.py` | Drawdown-breaker layer sweep (MA x DD-% breakers). |
| `strategies/fng_ab_test.py` | Fear & Greed A/B - proved F&G is a risk-trimmer, not a return-driver. |
| `strategies/lead_time_analysis.py` | Macro early-warning lead times (M2 YoY peaks ~8-11 months before tops; DXY 200MA reclaim leads). |
| `strategies/macro_regime.py` | v1 engine (F&G-only) - FAILED (whipsaw), kept for lineage. |
| `strategies/macro_backtest.py` | v1 backtest. |
| `strategies/macro_backtest_v2.py` | v2 backtest (200d-MA trend filter). |
| `strategies/build_btc_dataset.py` | Standalone BTC price builder (blockchain.info). |
| `strategies/backfill_derivatives.py` | Derivatives deep backfill (Deribit DVOL + Binance archive positioning/funding). Re-runnable; skips dates already present. Runs as part of `refresh.sh`. |
| `strategies/liquidity_map.py` | Modelled liquidation heatmap for BTC perps, free data only (no vendor API). Cohort model: each hour's traded volume is the weight of positions opened then, spread over low/mid/high, multiplied across a PUBLISHED leverage mix, run through the margin formula, decayed over 14 days and removed once price trades through the level. Prints the strongest shelves above (short liquidations) and below (long liquidations) plus an ASCII price-by-time grid. `--calibrate` A/B tests it against a permuted-volume null of itself using measured Gate liquidation flow. |
| `strategies/hold_benchmark.py` | THE BAR. Implements the 2026-11-04 judge verdict: 100% spot BTC, no timing, no rotation. Prints the four-window hold benchmark, a 1e-10 identity falsifier, the 200-day challenger under 20bp and one extra day of delay, and the ETH/BTC asset-selection diagnostic. Any proposed overlay must beat BTC hold by 1.10x in ALL FOUR windows or it is rejected. |
| `strategies/futures_vs_spot.py` | Futures-vs-spot leverage study (funding drag, liquidation math, constant vs regime-switched leveraged longs). Stateless; regenerate for numbers. |
| `scripts/refresh.sh` | On-demand refresh runner: fetch latest data (charts append daily) + re-run engine + audit. Run when the user asks for an update. `--check` = status only. |
| `data/macro_dataset/` | 98 charts, one CSV per series + `manifest.json` (source/span/rows per chart) + auto-generated README. |
| `data/macro/` | Gitignored scratch. Results are never committed - every script regenerates fresh and prints to stdout. |

## Refresh (on-demand, fetch + aggregate)

The data sources append new observations every day globally (Bitstamp, FRED,
Yahoo, blockchain.info, alternative.me, DefiLlama, ECB). The repo is **aware**
of this: it can fetch whatever is new and re-aggregate at any time, on any
system. There is NO cron/schedule - refresh happens only when asked:

- **User asks for an update** (or an agent decides a fresh read is needed):
  `bash scripts/refresh.sh` -> fetch latest charts -> re-run regime engine ->
  re-run audit -> on-chain confidence gate -> print verdict (stdout, nothing saved).
- **`bash scripts/refresh.sh --check`** -> status only (HEAD, last fetch,
  BTC data-through date). No saved verdict exists to report.
- **Hermes `macro` routines (owner-approved 2026-09-02; on the DEFAULT profile since the
  2026-09-10 consolidation - the `macro` profile no longer exists):** the owner's Hermes bot
  refreshes + commits + pushes the dataset every Sunday 20:00, and off-schedule
  when BTC moves >=7% in 24h, >=10% since the last committed close, or crosses
  its 200d MA. The repo itself remains schedule-free - no cron in repo code.
- **Daily on-chain append:** the bot's daily check also runs
  `build_macro_dataset.py --glassnode-only` and commits/pushes the `gn_*` charts
  (`Bot daily on-chain append <date>`). Those series are merge-only and can only
  be built forward - see the Glassnode row in Data pitfalls. Since 2026-10-02 the
  daily job is a silent no-op when no key is configured (keyless access ended
  2026-10-01; the paid route was ruled out) - the charts stay frozen until access
  returns.
- **Scope:** `scripts/refresh.sh` only refreshes LOCAL data + recomputes the
  verdict. It does NOT git-pull, does NOT push, does NOT schedule anything,
  does NOT save results. `build_macro_dataset.py` fetches keyless sources
  everywhere; FRED series run when `FRED_API_KEY` is set. If the user asks
  for an update and the network is down, report the error - never fabricate
  or use stale data silently.

## Commands

```bash
cd ~/projects/crypto-macro-analysis
./.venv/bin/python strategies/macro_regime_v3.py       # BTC engine -> verdict to stdout
./.venv/bin/python strategies/eth_macro_regime.py     # ETH engine -> verdict to stdout
./.venv/bin/python strategies/sol_macro_regime.py     # SOL engine -> verdict to stdout
./.venv/bin/python strategies/sol_macro_report.py     # SOL tape (daily + weekly + chain + derivatives)
./.venv/bin/python strategies/asset_tape.py --asset ZEC   # ZEC tape
./.venv/bin/python research/drawdown_state_study.py --asset ZEC  # state-conditional forward returns
./.venv/bin/python strategies/sol_macro_backtest.py   # SOL backtest + signal A/B
./.venv/bin/python strategies/audit_dataset.py         # signal checks (all pass)
./.venv/bin/python strategies/macro_backtest_v4.py     # composite backtest -> stdout
./.venv/bin/python strategies/eth_macro_backtest.py   # ETH backtest -> stdout
./.venv/bin/python strategies/macro_backtest_deep.py   # deep-history backtest -> stdout
./.venv/bin/python strategies/build_macro_dataset.py   # refresh dataset (slow, network)
./.venv/bin/python strategies/dd_protection_sweep.py   # DD layer sweep -> stdout
./.venv/bin/python strategies/liquidity_map.py          # modelled liquidation shelves -> stdout
./.venv/bin/python strategies/liquidity_map.py --coin SOL    # same model on Solana perps
./.venv/bin/python strategies/liquidity_map.py --calibrate   # A/B vs a permuted-volume null
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
- **Every `gn_*` chart has a point-in-time twin (`*_pit`) - know which one you are reading.**
  The live series is Glassnode's current best estimate and IS RESTATED as address clustering
  improves; `_pit` is immutable "as known then". Measured 2026-09-12 over the same 30 days:
  BTC netflow differed live-vs-PIT on 30/30 days (mean 232%, max 1,150%) and its 7-day sum
  flipped sign (+4,904 vs -19,494); balances/SOPR/NUPL differed by 0.2% or less; ETH netflow
  agreed to 0.2%. So: describe the regime with the live series, **backtest only on PIT or on
  the committed archive**, and never state a flow direction unless
  `strategies/onchain_confidence.py` prints CONFIRMED for it. A flow number quoted as fact
  without the gate is the exact failure this was built to prevent.
- **Glassnode MCP (`gn_*` charts, 42 series: 21 metrics x live + `_pit`) is a ROLLING
  30-DAY WINDOW.** The free public
  endpoint returns at most the last 30 days, so these charts are written with
  `merge_csv()` (merge by date, new wins) and never overwritten. The committed CSV
  is the history; a gap longer than 30 days is permanent. Do not "fix" a short
  gn_* chart by refetching - it cannot be backfilled for free.
- **Futures data from this box (2026-11-01):** Binance and Bybit public endpoints are geo-blocked
  (AWS/CloudFront country block); OKX, Gate and Deribit answer keyless. `liquidity_map.py` uses OKX
  hourly candles, Gate `contract_stats` (open interest, mark price, hourly long/short liquidation
  USD, 41 days hourly) and edgeornet for aggregate Binance+Bybit open interest. Coinglass's
  heatmap API refuses without a key and its heatmap endpoints sit on the Professional tier, so
  never build on it. Free intraday history is short everywhere: edgeornet keeps 7 days hourly and
  30 days at 4-hourly, OKX 30 days hourly, Coinalyze deletes intraday daily. Anything longer has to
  be accumulated locally.
- **The liquidation heatmap is a model, not a feed.** Levels come from open interest, an assumed
  leverage mix and the margin formula; they are not orders or stops. `--calibrate` in
  `liquidity_map.py` scores the shelves against a permuted-volume null using measured Gate
  liquidations: shelf locations reproduce an independent vendor model within about 1 percent, but
  the predictive edge over the null is weak and one-sided (downside), so use it as context.
- Glassnode's endpoint is Cloudflare-fronted: bare UAs get 403 "Just a moment",
  full browser headers (see `GN_HEADERS`) get 200. A Glassnode failure is
  fail-soft (WARN, not `FAILED`) so it cannot degrade the weekly refresh.
- **2026-10-01: keyless access ENDED.** The MCP now returns `401 -32001
  "Authentication required. Sign in with your Glassnode account, or supply an API
  key via the X-Api-Key header."` (the 2026-09-24 flap was the rehearsal).
  **2026-10-02: the paid route was ruled out (owner decision) - do not propose
  paid plans or OAuth.** The builder reads `GLASSNODE_API_KEY` from `.env` and
  sends `X-Api-Key` when set; without a key the on-chain section is SKIPPED (the
  daily job exits silently; charts stay frozen) and the weekly report prints a
  frozen marker instead of stale flow numbers. If a key is ever set, the fetch
  resumes automatically. While frozen, `gn_*` charts are historical-only - never
  quote them as live reads.

- **SOLANA (onboarded 2026-11-18).** Four source facts that will otherwise be rediscovered
  the hard way: (a) the longest keyless SOL daily price series is Yahoo's CCC aggregate
  `SOL-USD` from 2020-04-10 - Bitstamp only has SOL from 2022-08 and OKX from 2020-09, so
  Yahoo is the primary and OKX is the venue cross-check (audit enforces a 3% basis bound);
  (b) DefiLlama's Solana stablecoin chart is QUARTERLY SNAPSHOTS before 2023-01 (the first
  row is $8.7k, an artifact) - never compute a 30-day change there with a row offset;
  (c) Deribit's SOL DVOL index published only 2022-05-04 to 2022-11-25 and was then
  discontinued - it is not in the dataset and must not be re-proposed as a volatility
  source; (d) Binance's alt metrics archive starts 2021-12-01 for SOLUSDT (the perp is
  older, the archive is not; funding zips start 2021-01); (e) SOL.D and the ratio charts
  exist: `sol_dominance` is derived from `sol_mcap_cmc / cmc_total_mcap` (CoinMarketCap
  data-api - keyless but chunked at 350 days, or it silently samples), `solbtc_daily_okx`
  is the traded cross and `soleth_daily` is computed because OKX's SOL-ETH market is dead;
  (f) `bn_funding_sol` daily SUMS are huge in 2022-11-09..19 because Binance ran 2-hour
  funding at the -2 percent cap that week - 12 prints a day, not a parse error.
- **ZCASH (onboarded 2026-11-18).** (a) ZEC's first sessions printed 3,591 close / 20,000 high on
  slow-start supply - every ATH or drawdown read must start 2017-01-01 (`ath_from`), or the whole
  history looks "deep"; (b) CMC's ZEC supply has a phantom 10M print in 2017-18 and revision steps,
  so read the running maximum and only from 2022 on; (c) Bitfinex candles are MTS, OPEN, CLOSE,
  HIGH, LOW, VOLUME - not OHLC - and volume is in ZEC, so multiply by close for USD notional;
  (d) the shielded-pool balance has NO keyless source (zcashblockexplorer/zcha.in dead, blockchair
  current-only with an overflowing circulation field), so any privacy-adoption claim must be
  labelled unsourced; (e) ZEC has no DeFi, so there is no TVL/DEX/fee block - supply, issuance and
  positioning are its fundamentals.
- **`liquidity_map.py` follows `--coin` (fixed 2026-11-18).** The OKX instrument used to be
  hard-coded to `BTC-USDT-SWAP` while the open-interest lookup and the Gate calibration
  contract DID follow the coin, so `--coin SOL` modelled Bitcoin's shelves and labelled
  them Solana. Any new asset must be checked in the heatmap's title line (it prints the
  coin, the spot and the OI source) before its levels are quoted.

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
  the engine prints it to stdout. Qualitative context (2026-09-24): Phase 1
  risk-on (engine score positive); BTC crossed back above its 200d MA on
  2026-08-19 and has stayed above - the trend filter is IN the market again
  (it was in cash 2025-11-03 through 2026-08-19).
- **On-chain layer: FROZEN** (no new rows since 2026-10-01; the paid route was
  declined 2026-10-02). Treat `gn_*` charts as historical-only while frozen.
- Open items: gem-basket layer (regime filter on an
  alt basket); per-protocol usage data (DAU/fees) is paywalled (Artemis/TokenTerminal).
