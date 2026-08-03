"""MT5 connection + data fetch. Run on Windows with MT5 terminal installed."""
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import pytz

TZ_UTC = pytz.utc


def connect(login: int, password: str, server: str) -> bool:
    if not mt5.initialize():
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    ok = mt5.login(login, password=password, server=server)
    if not ok:
        raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")
    return True


def disconnect():
    mt5.shutdown()


def fetch_ohlcv(
    symbol: str,
    timeframe: int,  # e.g. mt5.TIMEFRAME_H1
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    start_utc = start.replace(tzinfo=TZ_UTC)
    end_utc = end.replace(tzinfo=TZ_UTC)
    rates = mt5.copy_rates_range(symbol, timeframe, start_utc, end_utc)
    if rates is None or len(rates) == 0:
        raise ValueError(f"No data for {symbol}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.rename(columns={"time": "Date", "open": "Open", "high": "High",
                             "low": "Low", "close": "Close", "tick_volume": "Volume"})
    return df.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]]


def save(df: pd.DataFrame, path: str):
    df.to_csv(path)
    print(f"Saved {len(df)} rows -> {path}")
