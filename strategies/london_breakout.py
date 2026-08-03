"""
London Breakout Strategy — H1 / M15
Edge: range of 7:00-9:00 AM GMT is broken in direction of breakout.
      Enter on first candle close outside range.
      SL: opposite side of range + 5 pips buffer.
      TP: 1.5x SL distance (RR 1:1.5).
      Exit: if no close by 13:00 GMT, exit flat.

Decades of documented positive expectancy on EURUSD, GBPUSD, XAUUSD.
Simple. No indicator dependency. Pure price action.
"""
from backtesting import Backtest, Strategy
import pandas as pd
import numpy as np


LONDON_OPEN_HOUR = 7   # GMT
LONDON_CLOSE_HOUR = 9  # GMT — range definition window
TRADE_DEADLINE_HOUR = 13  # GMT — force exit after this


class LondonBreakout(Strategy):
    rr = 3.0
    buffer_pips = 12
    pip_size = 0.0001   # EURUSD/GBPUSD; 0.1 for XAUUSD
    trend_ema = 50      # 0 = disabled; >0 = only trade in EMA direction

    def init(self):
        self._ema = self.I(
            lambda x: pd.Series(x).ewm(span=self.trend_ema, adjust=False).mean().values,
            self.data.Close,
            name=f"EMA{self.trend_ema}",
        ) if self.trend_ema > 0 else None

        self._range_high = None
        self._range_low = None
        self._range_date = None
        self._traded_today = False

    def next(self):
        dt = self.data.index[-1]
        hour = dt.hour
        date = dt.date()

        # Reset daily state on new day
        if self._range_date != date:
            self._range_high = None
            self._range_low = None
            self._range_date = date
            self._traded_today = False

        # Build range from 7-9 AM candles
        if LONDON_OPEN_HOUR <= hour < LONDON_CLOSE_HOUR:
            h = self.data.High[-1]
            l = self.data.Low[-1]
            self._range_high = max(self._range_high or h, h)
            self._range_low = min(self._range_low or l, l)
            return

        # Force exit after deadline
        if hour >= TRADE_DEADLINE_HOUR and self.position:
            self.position.close()
            return

        if self._traded_today or self._range_high is None:
            return

        buf = self.buffer_pips * self.pip_size
        close = self.data.Close[-1]
        rng = self._range_high - self._range_low

        if rng <= 0:
            return

        sl_dist = rng + buf
        tp_dist = sl_dist * self.rr

        # Trend filter: only trade in EMA direction
        ema_val = self._ema[-1] if self._ema is not None else None
        long_ok  = ema_val is None or close > ema_val
        short_ok = ema_val is None or close < ema_val

        # Breakout long
        if long_ok and close > self._range_high + buf:
            self.buy(sl=close - sl_dist, tp=close + tp_dist)
            self._traded_today = True

        # Breakout short
        elif short_ok and close < self._range_low - buf:
            self.sell(sl=close + sl_dist, tp=close - tp_dist)
            self._traded_today = True


def run_backtest(df: pd.DataFrame, cash: float = 10_000, commission: float = 0.0002):
    """
    df: OHLCV dataframe with DatetimeIndex in UTC.
    commission: 0.0002 = 2 pips spread equivalent.
    """
    bt = Backtest(df, LondonBreakout, cash=cash, commission=commission,
                  exclusive_orders=True)
    stats = bt.run()
    return bt, stats
