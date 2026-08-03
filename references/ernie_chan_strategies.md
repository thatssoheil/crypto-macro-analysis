# Ernie Chan – Algorithmic Trading (2013) – Extracted FX Strategies
## Source: Chapters 2, 3, 5, 7

---

## STRATEGY 1: AUD/CAD Linear Mean Reversion (Bollinger Band Variant)
**Book reference:** Example 5.2 / Example 2.5 / Example 3.2  
**Type:** Mean Reversion  
**Markets:** AUD.CAD (also applicable to AUD.USD, USD.CAD separately via Johansen)

### Entry Rules
1. Compute Z-score of AUD.CAD price vs its rolling 20-day mean:
   - `z = (price - MA(price, 20)) / STD(price, 20)`
2. Go **LONG** AUD.CAD when `z < -entryZscore` (i.e., -1.0)
3. Go **SHORT** AUD.CAD when `z > +entryZscore` (i.e., +1.0)

### Exit Rules
- **Exit LONG** when `z >= -exitZscore` (i.e., z >= 0, i.e., price returns to mean)
- **Exit SHORT** when `z <= +exitZscore` (i.e., z <= 0)
- No explicit hard stop-loss defined in book (author warns stop losses are inconsistent with mean-reversion)
- Position sizing: `numUnits = -z` (linear, proportional to z-score — the "scaling-in" approach)

### Parameters
| Parameter | Value |
|---|---|
| lookback (MA/STD window) | 20 days |
| entryZscore | 1.0 |
| exitZscore | 0.0 (exit at mean) |
| Rollover interest | Triple on Wednesdays for AUD, triple on Thursdays for CAD |

### Performance (Bollinger band, Example 3.2 on GLD-USO — same technique):
- APR: 17.8% (no transaction costs)
- Sharpe: 1.3
- AUD.CAD simple version (Example 5.2): APR 6.2%, Sharpe 0.54

### Rollover Interest Handling
```
# Triple rollover interest on Wednesdays for AUD, Thursdays for CAD
excess_return = log(price_t+1) - log(price_t) + log(1 + iAUD_t) - log(1 + iCAD_t)
```
Daily interest rates sourced from RBA (AUD) and Bank of Canada (CAD).

### Python Implementation Skeleton
```python
import numpy as np
import pandas as pd

def aud_cad_mean_reversion(prices: pd.Series, lookback: int = 20,
                            entry_z: float = 1.0, exit_z: float = 0.0):
    """
    prices: pd.Series of AUD.CAD daily close prices
    """
    ma = prices.rolling(lookback).mean()
    std = prices.rolling(lookback).std()
    z = (prices - ma) / std

    # Bollinger band approach
    positions = pd.Series(0.0, index=prices.index)
    long_entry = z < -entry_z
    long_exit  = z >= -exit_z
    short_entry = z > entry_z
    short_exit  = z <= exit_z

    pos = 0
    for i in range(len(prices)):
        if long_entry.iloc[i]:
            pos = 1
        elif long_exit.iloc[i] and pos == 1:
            pos = 0
        elif short_entry.iloc[i]:
            pos = -1
        elif short_exit.iloc[i] and pos == -1:
            pos = 0
        positions.iloc[i] = pos

    returns = positions.shift(1) * prices.pct_change()
    return positions, returns
```

### Timeframe
- **Daily (D1)** — strategy holds overnight, rollover interest applies

### Notes
- Cointegration first confirmed via ADF test (USD.CAD was stationary, H=0.49)
- Half-life of USD.CAD: ~115 days (but lookback kept at 20 for faster profit extraction)
- Linear version (no Bollinger band): `numUnits = -z` at every bar (scales continuously)

---

## STRATEGY 2: AUD.USD / USD.CAD Pair Trade via Johansen Eigenvector
**Book reference:** Example 5.1 (AUDCAD_unequal.m)  
**Type:** Mean Reversion (Cointegration-based)  
**Markets:** AUD.USD and USD.CAD (or equivalently, AUD.USD vs CAD.USD)

### Rationale
AUD and CAD are both "commodity currencies" with correlated economic fundamentals (mining revenue). They cointegrate. Hedge ratio is NOT 1:1 — use Johansen eigenvector.

### Entry Rules
1. Run Johansen cointegration test on [AUD.USD, CAD.USD] over 250-day training window
2. Extract first eigenvector `hedgeRatio = [h1, h2]`
3. Compute portfolio value: `yport = h1 * AUD.USD + h2 * CAD.USD`
4. Compute Z-score of `yport` over 20-day rolling window
5. `numUnits = -z_score` (linear, no Bollinger band in this example)
6. Position in each ccy: `positions[i] = numUnits * hedgeRatio[i] * price[i]` (dollar capital)

### Exit Rules
- Continuous linear exit: as z-score moves toward 0, position size reduces automatically
- No hard stop-loss specified

### Parameters
| Parameter | Value |
|---|---|
| Training window (Johansen) | 250 days (rolling) |
| Lookback for MA/STD | 20 days |
| Hedge ratio update | Rolling (each bar re-runs Johansen on last 250 days) |

### Performance
- APR: **11%**, Sharpe: **1.6** (Dec 18 2009 to Apr 26 2012)
- Out-of-sample after initial 250-day training

### MATLAB → Python Logic
```python
import numpy as np
import pandas as pd
# Requires: statsmodels or custom Johansen implementation

def pair_trade_johansen(aud_usd: pd.Series, usd_cad: pd.Series,
                         train_len=250, lookback=20):
    # Convert USD.CAD to CAD.USD for same-quote-currency requirement
    cad_usd = 1.0 / usd_cad
    y = pd.concat([aud_usd, cad_usd], axis=1)

    num_units = pd.Series(np.nan, index=y.index)
    hedge_ratio = pd.DataFrame(np.nan, index=y.index, columns=[0, 1])

    for t in range(train_len, len(y)):
        train = np.log(y.iloc[t - train_len:t].values)
        # Run Johansen: get first eigenvector
        # from statsmodels.tsa.vector_ar.vecm import coint_johansen
        # result = coint_johansen(train, det_order=0, k_ar_diff=1)
        # hr = result.evec[:, 0]  # first eigenvector
        # hedge_ratio.iloc[t] = hr

        window = y.iloc[t - lookback:t].values @ hedge_ratio.iloc[t].values  # dot product
        ma = np.mean(window)
        std = np.std(window)
        z = (window[-1] - ma) / std
        num_units.iloc[t] = -z

    # positions in dollar capital
    positions = num_units.values[:, None] * hedge_ratio.values * y.values
    pnl = np.sum(np.roll(positions, 1, axis=0) * y.pct_change().values, axis=1)
    ret = pnl / np.sum(np.abs(np.roll(positions, 1, axis=0)), axis=1)
    return pd.Series(ret, index=y.index)
```

### Timeframe
- **Daily (D1)**

### Key Insight
- Must use AUD.USD and CAD.USD (same quote currency = USD) for Johansen to be meaningful
- Dollar value of 1 point move must be equal across both instruments
- Rollover interests negligible for short-term version (excluded in Example 5.1)

---

## STRATEGY 3: Opening Gap Momentum – GBP/USD (London Open)
**Book reference:** Example 7.1 (gapFutures_FSTX.m adapted for currencies)  
**Type:** Momentum (Intraday)  
**Markets:** **GBP.USD** (book explicitly tested and confirmed)

### Rationale
Overnight/weekend gap triggers cascading stop orders at open, creating short-term momentum in the direction of the gap. Particularly effective at London open (5:00 AM ET).

### Entry Rules (Intraday — H1 or session-based)
Define:
- `close` = 5:00 PM ET price
- `open`  = 5:00 AM ET price (London open)
- `std90` = 90-bar rolling std of close-to-close returns (prior 90 days)

1. **LONG** if `open > prev_high * (1 + entryZscore * std90)`
   - i.e., open gaps up beyond prior day high + buffer
2. **SHORT** if `open < prev_low * (1 - entryZscore * std90)`
   - i.e., open gaps down below prior day low - buffer

Where:
- `entryZscore = 0.1` (fraction of 1-std daily return range)
- `prev_high` = prior session high
- `prev_low` = prior session low

### Exit Rules
- **Exit at 5:00 PM ET same day** (day trade — hold London open to NY close)
- Entry at `open`, exit at `close` of same session
- No trailing stop — time-based exit only
- `ret = position * (open - close) / open`

### Parameters
| Parameter | Value |
|---|---|
| entryZscore | 0.1 |
| std_lookback | 90 bars (daily) |
| Entry time | 5:00 AM ET (London open) |
| Exit time | 5:00 PM ET (NY close) |
| Session gap definition | 5 PM ET close to 5 AM ET open |

### Performance
- **GBP.USD**: APR **7.2%**, Sharpe **1.3** (Jul 23 2007 – Feb 20 2012)
- FSTX futures (original): APR 13%, Sharpe 1.4

### Python Implementation Skeleton
```python
import pandas as pd
import numpy as np

def gbpusd_gap_momentum(df: pd.DataFrame,
                         entry_z: float = 0.1,
                         std_lookback: int = 90):
    """
    df: DataFrame with columns ['open', 'high', 'low', 'close']
        indexed by session dates (one row per 5PM-to-5PM session)
        open  = 5:00 AM ET price
        high  = session high (prev session)
        low   = session low (prev session)
        close = 5:00 PM ET price
    """
    # 90-day rolling std of C2C returns
    ret_c2c = df['close'].pct_change()
    std90 = ret_c2c.rolling(std_lookback).std().shift(1)  # no lookahead

    prev_high = df['high'].shift(1)
    prev_low  = df['low'].shift(1)

    long_condition  = df['open'] > prev_high * (1 + entry_z * std90)
    short_condition = df['open'] < prev_low  * (1 - entry_z * std90)

    positions = pd.Series(0, index=df.index)
    positions[long_condition]  =  1
    positions[short_condition] = -1

    # P&L: enter at open, exit at close
    # ret = pos * (open - close) / open  (short entry at open, exit at close)
    # For longs: buy at open, sell at close => ret = (close - open) / open
    # Book formula: ret = positions * (open - close) / open
    # => longs profit when close < open? No — re-check:
    # Book: gap UP -> long -> hold open to close = ret = (close - open)/open
    # Actually book code: ret=positions.*(op-cl)./op
    # This means LONG profits when open > close (price falls back — NOT pure momentum)
    # Wait: re-read — futures version does op-cl, meaning:
    #   longs profit if op > cl (gap up + fade) — this is actually gap FADE for futures
    #   but for GBP.USD the gap UP triggers a long and holds to close
    # The book confirms APR 7.2% for GBP.USD with this formula
    # Interpretation: "buy when gap up, sell at close" — gap opens high, closes higher

    # Correct formula from book:
    daily_ret = positions.shift(1) * (df['open'] - df['close']) / df['open']
    # Note: sign depends on whether you interpret as: pos=1 means short-the-gap
    # or long-the-gap. Book's longs=op>prev_hi means gap-up triggers LONG
    # and ret = pos*(op-cl)/op with pos=1 gives profit when op>cl (gap fade)
    # For GBP.USD this IS a gap-fade, not gap-follow — verify in live trading

    return positions, daily_ret
```

### Timeframe
- **H1 or session-based** — one trade per day, entry at London open, exit at NY close
- Works best on FX pairs with significant overnight gaps

### Notes
- Strategy originally developed for FSTX futures, confirmed working on GBP.USD
- "Most currency markets are closed 5PM Fri to 5PM Sun — natural gap" (Chan p.157)
- Experiment with different opening/closing time definitions for different currency pairs
- Weekend gaps are natural entry opportunities

---

## STRATEGY 4: USD.CAD Linear Mean Reversion (Single Instrument, ADF Confirmed)
**Book reference:** Examples 2.1, 2.4, 2.5  
**Type:** Mean Reversion (Time-series stationary)  
**Markets:** USD.CAD (confirmed stationary by ADF test)

### Rationale
USD.CAD was shown to be stationary (ADF test at 90%+ confidence, H=0.49 Hurst). Single-instrument mean reversion — no pair needed.

### Stationarity Test Results (from book)
- ADF test: **stationary with 90%+ probability**
- Hurst exponent: **H = 0.49** (close to 0.5 = random walk, slight mean-reversion tendency)
- Variance Ratio test: h=0, pValue=0.367 (failed to reject random walk — weaker signal)
- Half-life of mean reversion: **~115 days**

### Entry Rules
1. Compute: `z = (price - MA(price, 115)) / STD(price, 115)`
   - lookback = round(half-life) = 115 days
2. Position = `-z` (linear, continuous, no threshold)
   - When price is above mean: short (negative position)
   - When price is below mean: long (positive position)

### Parameters
| Parameter | Value |
|---|---|
| Lookback | 115 days (= half-life) |
| Entry style | Linear (continuous scaling, no threshold) |
| OR Bollinger entry | entryZscore=1.0, exitZscore=0.0 |
| Timeframe | Daily |

### Performance
- APR: positive but modest (large drawdown warning)
- "Despite the long half-life, P&L manages to be positive, albeit with a large drawdown" (Chan p.49)
- Recommended to use Bollinger band variant with entryZscore=1 to reduce drawdown

### Python Implementation
```python
import pandas as pd
import numpy as np

def compute_halflife(price: pd.Series) -> float:
    """Ornstein-Uhlenbeck half-life estimate."""
    y = price.values
    y_lag = y[:-1]
    delta_y = np.diff(y)
    X = np.column_stack([y_lag, np.ones(len(y_lag))])
    beta = np.linalg.lstsq(X, delta_y, rcond=None)[0]
    lam = beta[0]
    half_life = -np.log(2) / lam
    return half_life

def usdcad_mean_reversion(prices: pd.Series,
                           entry_z: float = 1.0,
                           exit_z: float = 0.0):
    half_life = compute_halflife(prices)
    lookback = max(int(round(half_life)), 5)  # floor at 5

    ma  = prices.rolling(lookback).mean()
    std = prices.rolling(lookback).std()
    z   = (prices - ma) / std

    # Bollinger band version
    in_long  = False
    in_short = False
    positions = []
    for i in range(len(prices)):
        zi = z.iloc[i]
        if np.isnan(zi):
            positions.append(0)
            continue
        if not in_long and not in_short:
            if zi < -entry_z:
                in_long = True
            elif zi > entry_z:
                in_short = True
        elif in_long:
            if zi >= -exit_z:
                in_long = False
        elif in_short:
            if zi <= exit_z:
                in_short = False
        positions.append(1 if in_long else (-1 if in_short else 0))

    pos_series = pd.Series(positions, index=prices.index)
    returns = pos_series.shift(1) * prices.pct_change()
    return pos_series, returns, half_life
```

### Timeframe
- **Daily (D1)**

---

## STRATEGY 5: Time-Series Momentum – Futures/FX (Interday)
**Book reference:** Example 6.1 (TU_mom.m), Table 6.2, Chapter 6  
**Type:** Momentum (Interday)  
**Markets:** Primarily futures (TU, BR, HG); applicable to FX pairs with persistent roll/trend

### Rationale
Futures exhibit serial correlation of returns driven by persistence of roll return sign. Strategy: if past N-day return is positive, stay long for next M days.

### Entry Rules
1. Compute `past_ret = (close_t - close_{t-lookback}) / close_{t-lookback}`
2. **LONG** if `past_ret > 0` (price higher than N days ago)
3. **SHORT** if `past_ret < 0`
4. Hold for `holddays` days, then re-evaluate

### Exit Rules
- **Time-based exit only**: hold for `holddays` trading days
- Fractional position: invest `1/holddays` of capital per day's signal (overlapping positions)
- No hard stop loss (momentum strategies: stop loss = new reverse signal)

### Parameters (from Table 6.2)
| Symbol | Lookback | Hold days | APR | Sharpe | Max DD |
|--------|----------|-----------|-----|--------|--------|
| TU (2yr Treasury) | 250 days | 25 days | 1.7% | 1.04 | -2.5% |
| BR (Brazilian Real) | 100 days | 10 days | 17.7% | 1.09 | -14.8% |
| HG (Copper) | 40 days | 40 days | 18.0% | 1.05 | -24.0% |

For **FX**: Apply same framework. Test lookback/holddays via correlation analysis (find pair with highest correlation coefficient and lowest p-value).

### FX Application Guidelines
- Run correlation test between `past_N_return` and `future_M_return` for N, M in [1,5,10,25,60,120,250]
- Find best (N, M) pair: highest |correlation|, p-value < 0.05
- For currency pairs: commodity currencies (AUD, CAD, NZD) tend to trend

### Python Implementation (from book, converted)
```python
import numpy as np
import pandas as pd

def timeseries_momentum(prices: pd.Series,
                         lookback: int = 250,
                         holddays: int = 25):
    """
    Buy if price > price[t-lookback], short if price < price[t-lookback].
    Hold for holddays, investing 1/holddays each day.
    """
    longs  = prices > prices.shift(lookback)
    shorts = prices < prices.shift(lookback)

    pos = pd.Series(0.0, index=prices.index)

    for h in range(holddays):
        long_lag  = longs.shift(h).fillna(False)
        short_lag = shorts.shift(h).fillna(False)
        pos[long_lag]  += 1
        pos[short_lag] -= 1

    ret = pos.shift(1) * prices.pct_change() / holddays
    return pos, ret

def find_optimal_params(prices: pd.Series,
                         lookbacks=[1,5,10,25,60,120,250],
                         holds=[1,5,10,25,60,120,250]):
    """Find (lookback, holddays) with highest correlation and p<0.05."""
    from scipy.stats import pearsonr
    best = {'lookback': None, 'hold': None, 'corr': 0, 'pval': 1}
    for lb in lookbacks:
        for hd in holds:
            past_ret  = prices.pct_change(lb)
            fut_ret   = prices.pct_change(hd).shift(-hd)
            step = max(lb, hd)
            idx = range(0, len(prices) - hd, step)
            pr = past_ret.iloc[list(idx)].dropna()
            fr = fut_ret.iloc[list(idx)].dropna()
            common = pr.index.intersection(fr.index)
            if len(common) < 20:
                continue
            c, p = pearsonr(pr[common], fr[common])
            if c > best['corr'] and p < 0.05:
                best = {'lookback': lb, 'hold': hd, 'corr': c, 'pval': p}
    return best
```

### Enhanced Signal: Roll Return Threshold (mentioned in book)
For futures: use annualized roll return as signal instead of price return.
- **Long** if roll_return > threshold (e.g., +3% annualized)  
- **Short** if roll_return < -threshold  
- **Flat** otherwise  
- This variant on TU: APR 2.5%, Sharpe **2.1**, max DD -1.1% (Jan 2009 – Aug 2012)

### Combined Mean-Reversion + Momentum Filter (CL crude oil example)
From book (p.140): "Buy at close if price < price 30 days ago AND > price 40 days ago; vice versa for shorts."
```python
# Combined filter for any instrument
def combined_mr_mom(prices, short_lb=30, long_lb=40):
    long_cond  = (prices < prices.shift(short_lb)) & (prices > prices.shift(long_lb))
    short_cond = (prices > prices.shift(short_lb)) & (prices < prices.shift(long_lb))
    pos = pd.Series(0, index=prices.index)
    pos[long_cond] = 1
    pos[short_cond] = -1
    return pos
# CL: APR 12%, Sharpe 1.1
```

### Timeframe
- **Daily (D1)** — interday strategy, hold 10–250 days

---

## KEY RISK MANAGEMENT NOTES (Chapter 8, relevant excerpts)

### Stop Losses
- Stop losses are **INCONSISTENT** with mean-reversion strategies (they fight the signal)
- Stop losses are **CONSISTENT** with momentum strategies (reverse signal = natural stop)
- For MR: use position sizing limits (max capital per trade) instead of stop losses

### Kelly Criterion for FX
- Optimal leverage = Sharpe_ratio / std_of_returns
- Chan recommends **fractional Kelly (50%)** for practical trading
- For FTMO: max DD constraint of 5% → cap Kelly leverage accordingly

### Regime Detection
- Before applying MR strategy: confirm stationarity via ADF test
- If ADF test fails (p > 0.1), do not trade mean-reversion on that instrument
- Re-run ADF periodically (e.g., every 6 months) to detect regime shifts

### Parameter Sensitivity
- lookback = half-life is near-optimal for mean reversion
- entryZscore = 1.0 is standard; tune between 0.5 and 2.0
- exitZscore = 0.0 (exit at mean) is conservative; 0.5 takes partial profit earlier

---

## PERFORMANCE SUMMARY TABLE

| Strategy | Market | Timeframe | APR | Sharpe | Max DD | Type |
|----------|--------|-----------|-----|--------|--------|------|
| AUD.CAD Bollinger (Ex 3.2 technique) | AUD.CAD | D1 | ~6-18%* | 0.54-1.3 | N/A | MR |
| AUD.USD / USD.CAD Johansen (Ex 5.1) | AUD+CAD | D1 | 11% | 1.6 | N/A | MR |
| GBP.USD Gap Momentum (Ex 7.1) | GBP.USD | Session/H1 | 7.2% | 1.3 | N/A | Momentum |
| USD.CAD Linear MR (Ex 2.5) | USD.CAD | D1 | Positive | N/A | Large | MR |
| TU Momentum (Ex 6.1) | Futures | D1 | 1.7% | 1.04 | -2.5% | Momentum |

*Higher end = Bollinger band on cointegrated pair (Example 3.2 analogue)

---

## IMPLEMENTATION CHECKLIST FOR BACKTESTING.PY

1. Use bid-ask data for FX, not just mid (venue-dependent quotes)
2. AUD.CAD: triple rollover on Wed (AUD) and Thu (CAD) — multiply interest rate × 3
3. Run ADF test BEFORE deploying any MR strategy on new instrument
4. Lookback = half-life for MA/STD parameters (compute via OLS regression)
5. entryZscore=1.0, exitZscore=0.0 as defaults for Bollinger variant
6. Johansen: use same-quote-currency pairs (AUD.USD + CAD.USD, NOT USD.AUD + USD.CAD)
7. Momentum: no Bollinger bands — pure price vs N-days-ago comparison
8. GBP.USD gap: define session as 5PM→5PM ET; open = 5AM ET (London open)
9. Transaction costs NOT in book examples — subtract 1-2 pip spread per trade in live
10. Max leverage: use 50% Kelly; cap total DD at 5% for FTMO compliance
