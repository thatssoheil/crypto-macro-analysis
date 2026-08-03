"""
US30.cash open-drive / gap day-trade strategy (FTMO).

Rules (D1; H1 session version if H1 data present):
  At daily open (or first H1 of US cash session):
    Long  if open > prior high * (1 + entry_z * std90) OR open-drive up
    Short if open < prior low  * (1 - entry_z * std90) OR open-drive down
  Exit: same-day close (D1) or session end H1
  Risk: 1% equity, SL = atr_sl * ATR
  Symbol: US30.cash (FTMO MT5)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from backtesting import Strategy


def _atr_series(high, low, close, n=14):
    h, l, c = pd.Series(high), pd.Series(low), pd.Series(close)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()


class US30OpenDrive(Strategy):
    """D1 open-drive. Works on Yahoo proxy or FTMO D1 export."""

    entry_z = 0.0
    atr_sl = 1.5
    risk_pct = 0.01
    std_lookback = 90
    # FTMO US30.cash point value rough: contract 1, quote USD — size via cash
    ftmo_symbol = "US30.cash"

    def init(self):
        c = pd.Series(self.data.Close)
        h = pd.Series(self.data.High)
        l = pd.Series(self.data.Low)
        o = pd.Series(self.data.Open)

        std = c.pct_change().rolling(self.std_lookback).std().shift(1)
        atr = _atr_series(h, l, c).shift(1)

        self._std = self.I(lambda: std.fillna(0).values, name="std90")
        self._atr = self.I(lambda: atr.fillna(0).values, name="atr")
        self._ph = self.I(lambda: h.shift(1).fillna(h).values, name="prev_h")
        self._pl = self.I(lambda: l.shift(1).fillna(l).values, name="prev_l")
        self._pc = self.I(lambda: c.shift(1).fillna(c).values, name="prev_c")

    def next(self):
        if len(self.data) < self.std_lookback + 2:
            return

        o = float(self.data.Open[-1])
        c = float(self.data.Close[-1])
        atr = float(self._atr[-1])
        std = float(self._std[-1])
        ph, pl, pc = float(self._ph[-1]), float(self._pl[-1]), float(self._pc[-1])
        if atr <= 0 or std <= 0:
            return

        # Always flat overnight: close previous then decide today
        if self.position:
            self.position.close()

        long_gap = o > ph * (1 + self.entry_z * std)
        short_gap = o < pl * (1 - self.entry_z * std)
        drive_up = (o > pc) and ((o - pc) > 0.1 * atr) and not long_gap and not short_gap
        drive_dn = (o < pc) and ((pc - o) > 0.1 * atr) and not long_gap and not short_gap

        # Size: risk_pct of equity on atr_sl * ATR stop distance
        stop_dist = self.atr_sl * atr
        if stop_dist <= 0:
            return
        equity = self.equity
        risk_cash = equity * self.risk_pct
        # backtesting.py size as fraction of equity when 0<size<1
        # approx: loss if stop hit ≈ stop_dist/o * position_value
        # position_value = risk_cash * o / stop_dist
        frac = (risk_cash / equity) * (o / stop_dist)
        frac = float(np.clip(frac, 0.01, 0.95))

        sl_long = o - stop_dist
        sl_short = o + stop_dist

        if long_gap or drive_up:
            self.buy(size=frac, sl=sl_long)
        elif short_gap or drive_dn:
            self.sell(size=frac, sl=sl_short)


class US30SessionORB(Strategy):
    """
    H1 approximation of NY open ORB.
    Range = bars whose hour in [range_start_utc, range_end_utc)
    Entry next H1 close beyond range; exit by deadline_utc or SL.
    Default: 14:00-15:00 UTC ~ NY open hour (DST shifts — ponytail: exact M15 ET later).
    """

    range_start_utc = 14
    range_end_utc = 15
    deadline_utc = 20
    buffer_atr = 0.05
    atr_sl = 1.5
    rr = 2.0
    risk_pct = 0.01

    def init(self):
        h = pd.Series(self.data.High)
        l = pd.Series(self.data.Low)
        c = pd.Series(self.data.Close)
        atr = _atr_series(h, l, c)
        self._atr = self.I(lambda: atr.fillna(0).values, name="atr")
        self._day = None
        self._rh = None
        self._rl = None
        self._traded = False

    def next(self):
        ts = self.data.index[-1]
        # backtesting may use integer index — try .index from df
        try:
            t = pd.Timestamp(self.data.index[-1])
        except Exception:
            return
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        else:
            t = t.tz_convert("UTC")

        day = t.date()
        hour = t.hour
        atr = float(self._atr[-1])
        if atr <= 0:
            return

        if self._day != day:
            self._day = day
            self._rh = None
            self._rl = None
            self._traded = False
            if self.position:
                self.position.close()

        hi = float(self.data.High[-1])
        lo = float(self.data.Low[-1])
        cl = float(self.data.Close[-1])

        if self.range_start_utc <= hour < self.range_end_utc:
            self._rh = hi if self._rh is None else max(self._rh, hi)
            self._rl = lo if self._rl is None else min(self._rl, lo)
            return

        if hour >= self.deadline_utc:
            if self.position:
                self.position.close()
            return

        if self._traded or self._rh is None or self._rl is None:
            return
        if hour < self.range_end_utc:
            return

        buf = self.buffer_atr * atr
        stop_dist = self.atr_sl * atr
        equity = self.equity
        risk_cash = equity * self.risk_pct
        o = cl
        frac = float(np.clip((risk_cash / equity) * (o / stop_dist), 0.01, 0.95))

        if cl > self._rh + buf and not self.position:
            sl = cl - stop_dist
            tp = cl + self.rr * stop_dist
            self.buy(size=frac, sl=sl, tp=tp)
            self._traded = True
        elif cl < self._rl - buf and not self.position:
            sl = cl + stop_dist
            tp = cl - self.rr * stop_dist
            self.sell(size=frac, sl=sl, tp=tp)
            self._traded = True
