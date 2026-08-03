"""
Z-Score Mean Reversion (from Ernie Chan QT)
ADF confirmed stationary style on single pairs.
"""
import pandas as pd
import numpy as np
from backtesting import Strategy


class ZScoreMR(Strategy):
    lookback = 115   # Chan half-life approx for USD.CAD
    entry_z = 1.0
    exit_z = 0.0

    def init(self):
        idx = self.data.df.index
        close = pd.Series(self.data.Close, index=idx)

        # Convert daily halflife to H1 bars
        lb_bars = self.lookback * 24

        ma = close.rolling(lb_bars).mean()
        std = close.rolling(lb_bars).std()
        z = (close - ma) / std

        self._z = self.I(lambda: z.values, name="ZScore")

    def next(self):
        if len(self.data) < self.lookback * 24:
            return

        z = self._z[-1]

        if np.isnan(z):
            return

        if not self.position:
            if z < -self.entry_z:
                self.buy()
            elif z > self.entry_z:
                self.sell()
        elif self.position.is_long:
            if z >= -self.exit_z:
                self.position.close()
        elif self.position.is_short:
            if z <= self.exit_z:
                self.position.close()
