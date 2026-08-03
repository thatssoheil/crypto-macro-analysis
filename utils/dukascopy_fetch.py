"""Fetch H1 OHLCV from Dukascopy free tick feed. Monthly chunks, incremental write."""
import struct
import lzma
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests

SYMBOLS = {"EURUSD": 100000, "GBPUSD": 100000, "USDJPY": 1000, "XAUUSD": 1000}
TICK_FMT = ">IIIff"
TICK_SIZE = 20

# Global request-rate limiter: Dukascopy 429s on bursts.
_RATE_SLEEP = 0.15          # ~6-7 req/s ceiling (safe; 0.05 caused server resets)
_rate_lock = threading.Lock()
_last_req = 0.0

def _throttle():
    global _last_req
    with _rate_lock:
        dt = time.time() - _last_req
        if dt < _RATE_SLEEP:
            time.sleep(_RATE_SLEEP - dt)
        _last_req = time.time()

def fetch_hour(symbol: str, dt: datetime, divisor: int) -> list[tuple]:
    url = (
        f"https://datafeed.dukascopy.com/datafeed/{symbol}/"
        f"{dt.year}/{dt.month - 1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
    )
    for attempt in range(4):
        _throttle()
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 429:
                time.sleep(1.5 * (attempt + 1))  # backoff on rate-limit
                continue
            if r.status_code != 200 or len(r.content) < TICK_SIZE:
                return []
            raw = lzma.decompress(r.content)
            ticks = []
            for i in range(0, len(raw) - TICK_SIZE + 1, TICK_SIZE):
                ms, ask_r, bid_r, av, bv = struct.unpack(TICK_FMT, raw[i : i + TICK_SIZE])
                mid = ((ask_r + bid_r) / 2) / divisor
                ticks.append((dt + timedelta(milliseconds=ms), mid, av + bv))
            return ticks
        except Exception:
            time.sleep(0.5)
    return []


def ticks_to_ohlcv(ticks: list[tuple]) -> pd.DataFrame:
    if not ticks:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.DataFrame(ticks, columns=["time", "mid", "vol"]).set_index("time").sort_index()
    ohlcv = df["mid"].resample("1h").ohlc()
    ohlcv["Volume"] = df["vol"].resample("1h").sum()
    ohlcv.columns = ["Open", "High", "Low", "Close", "Volume"]
    return ohlcv.dropna(subset=["Open"])


def month_range(start: datetime, end: datetime):
    cur = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cur < end:
        if cur.month == 12:
            nxt = cur.replace(year=cur.year + 1, month=1)
        else:
            nxt = cur.replace(month=cur.month + 1)
        yield cur, min(nxt, end)
        cur = nxt


def fetch_month(symbol: str, divisor: int, start: datetime, end: datetime) -> pd.DataFrame:
    hours = []
    cur = start
    while cur < end:
        hours.append(cur)
        cur += timedelta(hours=1)
    all_ticks: list[tuple] = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(fetch_hour, symbol, h, divisor) for h in hours]
        for f in as_completed(futs):
            all_ticks.extend(f.result())
    return ticks_to_ohlcv(all_ticks)


def fetch_symbol(symbol: str, start: datetime, end: datetime, out_path: Path) -> int:
    divisor = SYMBOLS[symbol]
    parts = []
    for m_start, m_end in month_range(start, end):
        label = m_start.strftime("%Y-%m")
        print(f"  {symbol} {label}...", flush=True)
        df = fetch_month(symbol, divisor, m_start, m_end)
        if not df.empty:
            parts.append(df)
            print(f"  {symbol} {label}: {len(df)} bars", flush=True)
        else:
            print(f"  {symbol} {label}: empty", flush=True)
    if not parts:
        print(f"{symbol}: no data")
        return 0
    full = pd.concat(parts).sort_index()
    full = full[~full.index.duplicated(keep="first")]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    full.to_csv(out_path)
    print(f"{symbol}: {len(full)} candles -> {out_path}", flush=True)
    return len(full)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="all", help="EURUSD|GBPUSD|XAUUSD|all")
    p.add_argument("--start", default="2022-07-01")
    p.add_argument("--end", default="2024-07-01")
    p.add_argument("--out-dir", default="data")
    args = p.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    symbols = list(SYMBOLS) if args.symbol == "all" else [args.symbol.upper()]
    out_dir = Path(args.out_dir)

    total = 0
    for sym in symbols:
        total += fetch_symbol(sym, start, end, out_dir / f"{sym}_H1.csv")
    print(f"ALL DONE total_bars={total}", flush=True)
