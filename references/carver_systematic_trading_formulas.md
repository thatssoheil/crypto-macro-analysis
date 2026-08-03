# Robert Carver – Systematic Trading: Key Formulas & Rules
## Extracted for FX Algo Trading (EURUSD/GBPUSD H1, FTMO target)

---

## 1. POSITION SIZING FORMULA (CORE)

### Complete Pipeline
```
subsystem_position = (forecast × volatility_scalar) / 10
portfolio_position = subsystem_position × instrument_weight × IDM
```

### Step-by-step Variables

**Step 1: Price Volatility** (daily std dev of % returns)
```python
# Method A: Simple rolling
price_pct_returns = price.pct_change()
price_volatility = price_pct_returns.rolling(25).std()  # 25-day default

# Method B: EWMA (preferred — smoother, same half-life as 25-day SMA)
# Alpha = 2 / (1 + 36) = 0.054  (36-day lookback ≡ 25-day SMA)
alpha = 0.054
squared_returns = price_pct_returns ** 2
ewma_variance = squared_returns.ewm(alpha=alpha, adjust=False).mean()
price_volatility = ewma_variance.sqrt()
```
- Default lookback: **25 business days** (SMA) or **36 days** (EWMA)
- Units: fraction (e.g., 0.005 = 0.5% daily)

**Step 2: Block Value** (how much 1% price move is worth)
```python
# FX spot (e.g., EURUSD, lot = 100,000 base units):
# Block = 1 lot = 100,000 EUR
# Block value = 0.01 × 100,000 = $1,000 per 1% EURUSD move
block_value_usd = lot_size * 0.01  # $1,000 for standard lot EURUSD

# For mini lot (10,000): block_value = $100
# For micro lot (1,000): block_value = $10
```

**Step 3: Instrument Currency Volatility** (daily $ P&L std dev per 1 lot)
```python
instr_currency_vol = block_value * price_volatility
# e.g., $1000 * 0.006 = $6 per lot per day (for 0.6% daily vol)
```

**Step 4: Instrument Value Volatility** (in account currency)
```python
# If trading EURUSD with USD account: no conversion needed
# If trading GBPUSD with GBP account: multiply by USD/GBP rate
instr_value_vol = instr_currency_vol * fx_rate
# fx_rate: instrument_currency / account_currency
```

**Step 5: Daily Cash Volatility Target**
```python
annual_cash_vol_target = account_equity * pct_vol_target  # e.g., 0.25 = 25%
daily_cash_vol_target = annual_cash_vol_target / 16  # sqrt(256 business days)
```

**Step 6: Volatility Scalar**
```python
volatility_scalar = daily_cash_vol_target / instr_value_vol
# = number of lots to hold at forecast=10
```

**Step 7: Subsystem Position (lots)**
```python
subsystem_position = (forecast * volatility_scalar) / 10
# forecast range: -20 to +20, expected average absolute value = 10
# positive = long, negative = short
```

**Step 8: Portfolio Position (final)**
```python
portfolio_position = subsystem_position * instrument_weight * IDM
final_lots = round(portfolio_position)  # round only at end
# Apply position inertia: skip trade if current within 10% of target
```

---

## 2. VOLATILITY TARGETING

### Recommended % Volatility Targets (Half-Kelly)

| Realistic SR (after haircut) | Positive/zero skew | Negative skew |
|---|---|---|
| 0.25 | 12% | 6% |
| 0.40 | 20% | 10% |
| 0.50 | 25% | 12% |
| 0.75 | 37% | 19% |
| 1.0+ | 50% | 25% |

**Haircut rule**: Multiply back-tested SR by **0.75** (if using out-of-sample bootstrap) or less.
- Max realistic SR for systematic traders: **1.0**
- Author runs at 25% target personally (conservative)

**For FTMO context** (target 2-3%/month, max 5% DD):
- With Sharpe 0.854: realistic SR ≈ 0.854 × 0.75 ≈ 0.64 → vol target ~32%
- But FTMO 5% max DD → use conservative 10-15% vol target
- At 10% vol: expected worst daily loss ≈ $1,000 per $100k account

### Kelly Formula
```
optimal_vol_target = Sharpe_ratio  (full Kelly)
recommended_vol_target = Sharpe_ratio × 0.5  (half Kelly)
```

### Rolling Capital (update daily)
```python
current_capital = initial_capital + cumulative_pnl
annual_cash_vol_target = current_capital * pct_vol_target  # recalculate daily
```

---

## 3. FORECAST SCALING

### Forecast Properties
- Scale: expected **average absolute value = 10**
- Range: **capped at -20 to +20** (hard limits)
- +10 = average buy, -10 = average sell
- +20 = max long, -20 = max short, 0 = flat

### Forecast Scalar (for custom rules)
```python
# Back-test rule to get average absolute forecast
avg_abs_forecast = historical_forecasts.abs().mean()
forecast_scalar = 10 / avg_abs_forecast
scaled_forecast = raw_forecast * forecast_scalar
capped_forecast = np.clip(scaled_forecast, -20, 20)
```

### EWMAC Forecast Scalars (pre-computed, from author's research)
| EWMAC Variant | Forecast Scalar |
|---|---|
| EWMAC(2, 8)   | 10.6 |
| EWMAC(4, 16)  | 7.5  |
| EWMAC(8, 32)  | 5.3  |
| EWMAC(16, 64) | 3.75 |
| EWMAC(32,128) | 2.65 |
| EWMAC(64,256) | 1.87 |

### Carry Rule Forecast Scalar
- Always **30** (across all asset classes)
- Turnover ≈ **10 round trips/year** (update weekly)

---

## 4. EWMAC TRADING RULE

```python
def ewmac_forecast(prices, fast_span, slow_span, forecast_scalar):
    """
    Exponentially Weighted Moving Average Crossover.
    fast_span/slow_span: look-back in days (ratio should be ~4)
    Recommended pairs: (2,8), (4,16), (8,32), (16,64), (32,128), (64,256)
    """
    # Decay: A = 2 / (L + 1)
    fast_ewma = prices.ewm(span=fast_span, adjust=False).mean()
    slow_ewma = prices.ewm(span=slow_span, adjust=False).mean()
    
    raw_crossover = fast_ewma - slow_ewma  # in price units
    
    # Std dev in price points (not %)
    price_vol_pct = prices.pct_change().ewm(span=36).std()
    price_vol_pts = price_vol_pct * prices  # convert to price units
    
    vol_adj_crossover = raw_crossover / price_vol_pts
    forecast = vol_adj_crossover * forecast_scalar
    return np.clip(forecast, -20, 20)
```

**Rule of thumb correlations between EWMAC variants (same instrument):**
| | EW2 | EW4 | EW8 | EW16 | EW32 | EW64 |
|---|---|---|---|---|---|---|
| EW2  | 1.0  | 0.90 | 0.60 | 0.35 | 0.20 | 0.15 |
| EW4  | —    | 1.0  | 0.90 | 0.60 | 0.40 | 0.20 |
| EW8  | —    | —    | 1.0  | 0.90 | 0.65 | 0.45 |
| EW16 | —    | —    | —    | 1.0  | 0.90 | 0.70 |
| EW32 | —    | —    | —    | —    | 1.0  | 0.90 |

Adjacent variants: **0.90** correlation. Prune variants with >0.95 correlation (adds no value).

---

## 5. COMBINING MULTIPLE FORECASTS (FDM)

### Formula
```python
# Step 1: Weighted average of individual forecasts
raw_combined = sum(forecast_i * weight_i for i in rules)

# Step 2: Forecast Diversification Multiplier (FDM)
# Given: correlation matrix H (N×N), weights W (N,)
import numpy as np
def calc_fdm(weights, corr_matrix):
    W = np.array(weights)
    H = np.array(corr_matrix)
    H_floored = np.maximum(H, 0)  # floor negative correlations at 0
    portfolio_variance = W @ H_floored @ W
    fdm = 1.0 / np.sqrt(portfolio_variance)
    return min(fdm, 2.5)  # hard cap at 2.5

# Step 3: Apply FDM
rescaled_combined = raw_combined * fdm

# Step 4: Cap
final_forecast = np.clip(rescaled_combined, -20, 20)
```

### FDM Lookup Table (approximate, equal weights)
| N rules | Avg corr=0.0 | 0.25 | 0.50 | 0.75 | 1.0 |
|---|---|---|---|---|---|
| 2 | 1.41 | 1.27 | 1.15 | 1.10 | 1.0 |
| 3 | 1.73 | 1.41 | 1.22 | 1.12 | 1.0 |
| 4 | 2.0  | 1.51 | 1.27 | 1.10 | 1.0 |
| 5 | 2.2  | 1.58 | 1.29 | 1.15 | 1.0 |

**Max FDM: 2.5** (hard cap regardless of calculation)

### Typical Rule Correlations (same instrument)
- Same rule, adjacent variants: **0.90**
- Same style (e.g., EWMAC fast vs slow): **0.70**
- Different styles (EWMAC vs Carry): **0.25**
- Different styles, same category: **0.50**

### Handcrafted Forecast Weights Example (EWMAC + Carry)
```
Group 1 – EWMAC (3 variants, avg corr ~0.7):
  EWMAC(16,64):  42% of group → 42% × 50% = 21% final
  EWMAC(32,128): 16% of group → 16% × 50% = 8%  final
  EWMAC(64,256): 42% of group → 42% × 50% = 21% final

Group 2 – Carry (1 variant):
  Carry: 100% of group → 100% × 50% = 50% final

FDM for this combo (avg corr ≈ 0.50, 4 variants): ≈ 1.27
```

---

## 6. PORTFOLIO CONSTRUCTION (INSTRUMENT WEIGHTS + IDM)

### Instrument Diversification Multiplier (IDM)
```python
def calc_idm(instrument_weights, subsystem_corr_matrix):
    """Same formula as FDM but uses subsystem return correlations."""
    W = np.array(instrument_weights)
    H = np.array(subsystem_corr_matrix)
    H_floored = np.maximum(H, 0)
    idm = 1.0 / np.sqrt(W @ H_floored @ W)
    return min(idm, 2.5)  # hard cap
```

### Correlation Adjustment for Dynamic Systems
- Instrument return correlations → multiply by **0.7** for subsystem correlations
- Static (asset allocator): use correlations as-is (no adjustment)

### Approximate Correlation Table (FX)
| | Bonds | Equities | FX | Commodities |
|---|---|---|---|---|
| FX | 0.1 | 0.1 | 1.0 | 0.25 |
- FX pairs in same region, vs USD: **0.75** (e.g., EURUSD vs GBPUSD)
- FX emerging vs developed: **0.15**

### Instrument Weights – Handcrafting
```
For 2 FX pairs (EURUSD + GBPUSD), same region (corr ≈ 0.75):
  Equal weights: 50% each
  Subsystem corr = 0.75 × 0.7 = 0.525 (dynamic strategy)
  IDM = 1 / sqrt(0.5*0.5*1 + 0.5*0.5*1 + 2*0.5*0.5*0.525)
       = 1 / sqrt(0.5 + 0.2625) = 1 / sqrt(0.7625) ≈ 1.15
```

### Portfolio Position (Final Formula)
```python
portfolio_position = subsystem_position × instrument_weight × IDM
final_lots = round(portfolio_position)

# Position inertia: only trade if current position is >10% away from target
inertia_threshold = 0.10
if abs(current_lots - final_lots) / max(abs(final_lots), 1) <= inertia_threshold:
    pass  # skip trade
else:
    trade = final_lots - current_lots
```

---

## 7. RISK PER TRADE (VOLATILITY TARGET TRANSLATION)

### Implied Volatility from Traditional % Risk
Table for 2 positions open simultaneously:

| Holding period | 1% risk/trade | 2.5% | 5% | 10% |
|---|---|---|---|---|
| 1 day  | 40% vol | 100% | 200% | ! |
| 1 week | 16% vol | 40%  | 80%  | 160% |
| 2 weeks| 8% vol  | 19%  | 38%  | 76% |
| 6 weeks| 4% vol  | 10%  | 21%  | 41% |
| 3 months| 3% vol | 7%   | 13%  | 27% |

**Multiply/divide proportionally for different N open positions.**

### For FTMO (5% max DD, H1 timeframe ≈ few-day holds)
- Hold ~1 week → target 8-16% annual vol → use 10% conservatively
- At 10% vol, $100k: daily target = $100k × 0.10 / 16 = **$625/day**
- Risk per lot EURUSD ≈ daily std dev × lot_size
- If EURUSD daily vol = 0.6%: $1000 × 0.006 = $6/lot/day
- Lots to hold at forecast=10: $625 / $6 = **104 lots** (for 100% allocation)
- With instrument weight 50% and IDM 1.15: 104 × 0.50 × 1.15 ≈ **60 lots**

---

## 8. FX-SPECIFIC NOTES

### Block Value for FX Spot/CFD
```python
# Standard lot: 100,000 base currency
# 1% price move on EURUSD = 0.01 × 100,000 = $1,000 (quoted in USD)
block_value = lot_size * 0.01  # in quote currency

# Mini lot (10,000): $100 per 1%
# Micro lot (1,000): $10 per 1%
```

### FX Carry Rule
```python
# For FX cash:
net_expected_return_pct = foreign_interest_rate - domestic_interest_rate
net_expected_return_price = net_expected_return_pct * current_price  # annualised, in price units

# Annualised price vol
daily_price_vol_pts = price_vol_pct * price
annual_price_vol_pts = daily_price_vol_pts * 16  # sqrt(256)

raw_carry = net_expected_return_price / annual_price_vol_pts  # Sharpe-like
forecast = np.clip(raw_carry * 30, -20, 20)  # scalar=30
```

### FX-Specific Warnings (direct from Carver)
1. **Swiss franc (CHF) event Jan 2015**: Near-zero vol → massive position → 16% gap → wipeout. At 50× leverage: zero surviving. Max safe leverage ~7×.
2. **Avoid very low-vol FX pairs**: CHF pairs at 1%/year → to hit 50% vol target needs 50× leverage. **Do not trade**.
3. **EUR/CHF example**: Survived only if <10% portfolio weight when gap hit.
4. **FX carry** has **negative skew** → run at half the normal vol target.
5. **EURUSD/GBPUSD correlation ≈ 0.75** → if trading both, IDM ≈ 1.15, weights 50/50.

---

## 9. COMPLETE PYTHON IMPLEMENTATION TEMPLATE

```python
import numpy as np
import pandas as pd

def price_volatility_ewma(prices, span=36):
    """Daily % vol, EWMA method (default span=36 equiv to 25-day SMA)."""
    returns = prices.pct_change()
    return returns.ewm(span=span).std()

def instrument_value_vol(price_vol, block_value, fx_rate=1.0):
    """Daily std dev of 1 block in account currency."""
    return block_value * price_vol * fx_rate

def daily_cash_vol_target(capital, pct_target):
    """Annual -> daily cash vol target."""
    return capital * pct_target / 16.0

def volatility_scalar(daily_target, instr_value_vol):
    """Lots to hold at forecast=10."""
    return daily_target / instr_value_vol

def subsystem_position(forecast, vol_scalar):
    """Raw position in lots (unrounded)."""
    return (np.clip(forecast, -20, 20) * vol_scalar) / 10.0

def calc_diversification_multiplier(weights, corr_matrix, cap=2.5):
    """FDM or IDM. Floor negative corrs at 0."""
    W = np.array(weights, dtype=float)
    H = np.maximum(np.array(corr_matrix, dtype=float), 0)
    port_var = W @ H @ W
    dm = 1.0 / np.sqrt(port_var)
    return min(dm, cap)

def portfolio_position(subsys_pos, instr_weight, idm):
    """Final unrounded position."""
    return subsys_pos * instr_weight * idm

def apply_position_inertia(current, target, threshold=0.10):
    """Skip trade if within threshold% of target."""
    if target == 0:
        return target if current != 0 else current
    if abs(current - target) / abs(target) <= threshold:
        return current  # no trade
    return target

def ewmac_forecast(prices, fast, slow, scalar):
    """EWMAC trading rule. fast:slow ratio should be ~4."""
    fast_ema = prices.ewm(span=fast, adjust=False).mean()
    slow_ema = prices.ewm(span=slow, adjust=False).mean()
    raw = fast_ema - slow_ema
    price_vol_pts = prices.pct_change().ewm(span=36).std() * prices
    vol_adj = raw / price_vol_pts.replace(0, np.nan)
    return np.clip(vol_adj * scalar, -20, 20)

def combine_forecasts(forecasts, weights, corr_matrix):
    """
    forecasts: list of pd.Series
    weights: list of floats summing to 1
    corr_matrix: list of lists
    Returns: final combined forecast Series
    """
    raw = sum(f * w for f, w in zip(forecasts, weights))
    fdm = calc_diversification_multiplier(weights, corr_matrix)
    return np.clip(raw * fdm, -20, 20)

# ---- USAGE FOR EURUSD H1 ----
# capital = 100_000  # USD
# pct_target = 0.10  # 10% annual vol (conservative FTMO)
# lot_size = 100_000  # standard lot
# block_value = lot_size * 0.01  # $1,000 per 1% move
# 
# price_vol = price_volatility_ewma(eurusd_daily_close)  # use daily closes
# iv_vol = instrument_value_vol(price_vol, block_value)   # ~$6/lot/day at 0.6% vol
# daily_target = daily_cash_vol_target(capital, pct_target)  # $625
# vol_sc = volatility_scalar(daily_target, iv_vol)           # ~104 lots
#
# forecast = ewmac_forecast(eurusd_daily_close, 8, 32, 5.3)  # EWMAC(8,32) for H1
# subsys = subsystem_position(forecast, vol_sc)
# port = portfolio_position(subsys, 0.50, 1.15)   # 50% weight, IDM=1.15
# final_lots = apply_position_inertia(current_lots, round(port))
```

---

## 10. PARAMETER SUMMARY

| Parameter | Default | Notes |
|---|---|---|
| Vol lookback (SMA) | 25 business days | Industry standard |
| Vol lookback (EWMA) | 36 days (α=0.054) | Equiv to 25-day SMA |
| Forecast target abs value | 10 | All rules must be scaled to this |
| Forecast cap | ±20 | Hard limit always |
| FDM cap | 2.5 | Avoids runaway positions |
| IDM cap | 2.5 | Same |
| Position inertia | 10% | Skip trade if within 10% of target |
| Kelly multiplier | 0.5 | Use half-Kelly always |
| SR haircut | 0.75 | For out-of-sample bootstrap |
| EWMAC fast:slow ratio | 4:1 | e.g., 8:32, 16:64 |
| Carry scalar | 30 | All asset classes |
| Min correlation floor | 0 | Negative corrs → 0 in DM calculation |
| Business days/year | 256 | sqrt = 16 (annualize/dailyze) |
| Subsystem corr adj | 0.7× | Dynamic systems: multiply instrument corr by 0.7 |
