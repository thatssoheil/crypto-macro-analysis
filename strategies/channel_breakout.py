"""
Donchian Channel Breakout (from Aronson / Dunn & Hargitt)
One of the few fully validated strategies on FX futures.
Works best on Daily bars, tested here on H1 with scaled N.
"""
import pandas as pd
from backtesting import Strategy


class ChannelBreakout(Strategy):
    n_days = 20
    pip_size = 0.0001
    atr_sl = 2.0      # ATR trailing stop

    def init(self):
        idx = self.data.df.index
        close = pd.Series(self.data.Close, index=idx)
        high = pd.Series(self.data.High, index=idx)
        low = pd.Series(self.data.Low, index=idx)

        # Convert n_days to H1 bars approx (24h)
        n_bars = self.n_days * 24

        # Donchian channel limits (shifted 1 so current bar doesn't trigger itself)
        highest = high.rolling(n_bars).max().shift(1)
        lowest = low.rolling(n_bars).min().shift(1)

        self._upper = self.I(lambda: highest.values, name="Upper")
        self._lower = self.I(lambda: lowest.values, name="Lower")

        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(24*14).mean()
        self._atr = self.I(lambda: atr.values, name="ATR")

    def next(self):
        if len(self.data) < self.n_days * 24:
            return

        c = self.data.Close[-1]
        u = self._upper[-1]
        l = self._lower[-1]
        atr = self._atr[-1]

        # Stop loss adjustment (trailing)
        if self.position.is_long:
            self.position.sl = max(self.position.sl or 0, c - atr * self.atr_sl)
        elif self.position.is_short:
            self.position.sl = min(self.position.sl or float('inf'), c + atr * self.atr_sl)

        # Breakout long
        if c > u and not self.position.is_long:
            self.position.close()
            self.buy(sl=c - atr * self.atr_sl)
        # Breakout short
        elif c < l and not self.position.is_short:
            self.position.close()
            self.sell(sl=c + atr * self.atr_sl)
