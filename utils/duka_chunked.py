#!/usr/bin/env python3
"""Chunked, resumable Dukascopy H1 fetch. Falls back to existing partial file."""
import sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import dukascopy_fetch as d
import pandas as pd

SYMS = {"EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY", "XAUUSD": "XAUUSD"}

def fetch_range(symbol, start, end, out):
    parts = []
    cur = start
    if out.exists():
        try:
            old = pd.read_csv(out, index_col=0, parse_dates=True)
            old.index = pd.to_datetime(old.index, utc=True)
            old = old[~old.index.duplicated(keep='first')]
            parts.append(old)  # keep ALL existing bars
            # resume from the first full month AFTER the last captured bar
            last = old.index.max()
            if pd.notna(last):
                nxt = last + timedelta(hours=1)
                cur = nxt.replace(day=1, hour=0, minute=0, second=0)
                print(f"  resuming from last bar {last:%Y-%m-%d %H:%M} -> next month {cur:%Y-%m}", flush=True)
        except Exception as e:
            print("existing partial unreadable:", e)
    while cur < end:
        if cur.month == 12:
            nxt = cur.replace(year=cur.year + 1, month=1)
        else:
            nxt = cur.replace(month=cur.month + 1)
        nxt = min(nxt, end)
        label = cur.strftime("%Y-%m")
        print(f"  {symbol} {label}...", flush=True)
        df = d.fetch_month(symbol, d.SYMBOLS[symbol], cur, nxt)
        if not df.empty:
            parts.append(df)
            print(f"  {symbol} {label}: {len(df)} bars", flush=True)
            # checkpoint after each month
            full = pd.concat(parts).sort_index()
            full = full[~full.index.duplicated(keep='first')]
            out.parent.mkdir(parents=True, exist_ok=True)
            full.to_csv(out)
            print(f"  checkpoint {len(full)} candles -> {out.name}", flush=True)
        else:
            print(f"  {symbol} {label}: empty (retrying later)", flush=True)
            time.sleep(2)
        cur = nxt
    return len(pd.read_csv(out, index_col=0, parse_dates=True)) if out.exists() else 0

if __name__ == "__main__":
    sym = sys.argv[1]
    start = datetime.fromisoformat(sys.argv[2]).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(sys.argv[3]).replace(tzinfo=timezone.utc)
    out = Path(sys.argv[4])
    print(f"Fetching {sym} {start:%Y-%m} -> {end:%Y-%m} to {out}")
    n = fetch_range(sym, start, end, out)
    print(f"DONE {sym}: {n} candles")
