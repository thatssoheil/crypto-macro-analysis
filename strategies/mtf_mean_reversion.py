"""
Multi-Timeframe Mean Reversion Strategy v2
===========================================
Logic:
  W1 bias:   W1 close > W1 EMA20 = bullish, only longs. Below = only shorts.
  D1 setup:  Price at/below D1 EMA21 (longs) or at/above (shorts)
  H1 entry:  RSI(14) < 30 oversold (long) or > 70 overbought (short)
             + price bouncing (close > open for long, close < open for short)
  SL:        ATR-based (1x ATR below entry for long)
  TP:        RR x SL distance
  Filter:    Max 1 trade per day. ATR normal range only.
"""
import pandas as pd
import numpy as np
from backtesting import Backtest, Strategy


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


class MTFMeanReversion(Strategy):
    pip_size      = 0.0001
    rr            = 2.5
    atr_sl_mult   = 1.0       # SL = atr_sl_mult * ATR
    ema_zone_pips = 40        # price within X pips of D1 EMA to qualify
    rsi_long      = 35        # RSI threshold for long entry (oversold)
    rsi_short     = 65        # RSI threshold for short entry (overbought)
    atr_max_mult  = 1.8       # skip if ATR > X * avg (news day)
    atr_min_mult  = 0.5       # skip if ATR < X * avg (dead market)
    w1_ema        = 20
    d1_ema        = 21
    rsi_period    = 14

    def init(self):
        idx   = self.data.df.index
        close = pd.Series(self.data.Close, index=idx)
        high  = pd.Series(self.data.High,  index=idx)
        low   = pd.Series(self.data.Low,   index=idx)

        # ATR
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.ewm(span=14, adjust=False).mean()
        self._atr     = self.I(lambda: atr.values, name='ATR')
        self._atr_avg = self.I(lambda: atr.rolling(100, min_periods=1).mean().values, name='ATR_avg')

        # RSI on H1
        rsi = _rsi(close, self.rsi_period)
        self._rsi = self.I(lambda: rsi.values, name='RSI')

        # D1 EMA (resample then ffill)
        d1_close = close.resample('1D').last().ffill()
        d1_ema   = d1_close.ewm(span=self.d1_ema, adjust=False).mean().reindex(idx, method='ffill')
        self._d1_ema = self.I(lambda: d1_ema.values, name='D1_EMA')

        # W1 EMA
        w1_close = close.resample('1W').last().ffill()
        w1_ema   = w1_close.ewm(span=self.w1_ema, adjust=False).mean().reindex(idx, method='ffill')
        self._w1_ema = self.I(lambda: w1_ema.values, name='W1_EMA')

        self._last_trade_date = None

    def next(self):
        if len(self.data) < 150:
            return

        dt     = self.data.index[-1]
        today  = dt.date()
        close  = self.data.Close[-1]
        open_  = self.data.Open[-1]
        atr    = self._atr[-1]
        atr_avg= self._atr_avg[-1]
        rsi    = self._rsi[-1]
        d1_ema = self._d1_ema[-1]
        w1_ema = self._w1_ema[-1]

        # ATR filter
        if atr < atr_avg * self.atr_min_mult or atr > atr_avg * self.atr_max_mult:
            return

        # Max 1 trade per day
        if self._last_trade_date == today:
            return

        # Already in trade
        if self.position:
            return

        zone   = self.ema_zone_pips * self.pip_size
        sl_d   = atr * self.atr_sl_mult
        tp_d   = sl_d * self.rr

        # LONG: W1 bull + price near/below D1 EMA + RSI oversold + bullish candle
        if (close > w1_ema and
                close <= d1_ema + zone and
                rsi < self.rsi_long and
                close > open_):
            self.buy(sl=close - sl_d, tp=close + tp_d)
            self._last_trade_date = today

        # SHORT: W1 bear + price near/above D1 EMA + RSI overbought + bearish candle
        elif (close < w1_ema and
                close >= d1_ema - zone and
                rsi > self.rsi_short and
                close < open_):
            self.sell(sl=close + sl_d, tp=close - tp_d)
            self._last_trade_date = today


def run_backtest(df: pd.DataFrame, cash: float = 10_000, commission: float = 0.0001):
    bt = Backtest(df, MTFMeanReversion, cash=cash, commission=commission,
                  exclusive_orders=True)
    return bt, bt.run()

