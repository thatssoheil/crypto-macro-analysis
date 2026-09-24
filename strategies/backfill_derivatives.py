#!/usr/bin/env python3
"""One-time deep backfill for the derivatives charts (source-hunt batch 2b).

Sources (all keyless, verified working 2026-09-24):
  - Deribit DVOL daily closes (BTC, ETH) via public API (paginated, 1000 pts/call)
  - Binance USD-M futures daily metrics zips (data.binance.vision): open interest,
    top-trader long/short ratio, taker buy/sell volume ratio -> daily (23:45 snapshot)
  - Binance monthly fundingRate zips -> daily SUM of the 8h rates (fraction/day)

Writes into data/macro_dataset/ (merge-by-date: existing rows kept, new rows win).
Re-runnable: skips metric dates already present in the CSVs, so after the first
pass it is cheap. The committed CSVs are the history; the builder only appends
recent days.

Run: ./.venv/bin/python strategies/backfill_derivatives.py
"""
import csv
import io
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(__file__).parent.parent / "data" / "macro_dataset"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) dataset-builder"}
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
BZ = "https://data.binance.vision"
METRIC_COLS = {"sum_open_interest": "oi",
               "sum_toptrader_long_short_ratio": "lsr",
               "sum_taker_long_short_vol_ratio": "taker"}
FUND_COLS = ["calc_time", "funding_interval_hours", "last_funding_rate"]


def get(url, tries=3, wait=2):
    for i in range(tries):
        try:
            r = requests.get(url, timeout=60, headers=UA)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
            time.sleep(wait * (i + 1))
        except Exception:
            time.sleep(wait * (i + 1))
    return None


def load_existing(name):
    p = OUT / f"{name}.csv"
    d = {}
    if p.exists():
        with open(p, newline="") as f:
            rd = csv.reader(f)
            next(rd, None)
            for row in rd:
                if row and row[0]:
                    d[row[0]] = row[1]
    return d


def write(name, d):
    rows = sorted(d.items())
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "value"])
        w.writerows(rows)
    print(f"  wrote {name}.csv: {len(rows)} rows -> {rows[-1][0] if rows else '-'}", flush=True)


def csv_lines(blob):
    z = zipfile.ZipFile(io.BytesIO(blob))
    lines = [l for l in z.read(z.namelist()[0]).decode().splitlines() if l.strip()]
    if lines and lines[0].startswith("create_time") or (lines and lines[0].startswith("calc_time")):
        return lines[0].split(","), lines[1:]
    return None, lines


# ---------- 1. Deribit DVOL ----------
print("== Deribit DVOL (full history) ==", flush=True)
for cur, name in (("BTC", "dvol_btc"), ("ETH", "dvol_eth")):
    d = load_existing(name)
    start = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    cursor = int(time.time() * 1000)
    calls = 0
    while calls < 6:
        r = get(f"https://www.deribit.com/api/v2/public/get_volatility_index_data"
                f"?currency={cur}&start_timestamp={start}&end_timestamp={cursor}&resolution=1D")
        if not r:
            break
        data = (r.json().get("result") or {}).get("data") or []
        if not data:
            break
        for ts, o, h, l, c in data:
            dd = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            d[dd] = str(c)
        calls += 1
        oldest = data[0][0]
        if len(data) < 1000 or oldest <= start:
            break
        cursor = oldest - 1
        time.sleep(0.3)
    write(name, d)

# ---------- 2. Binance daily metrics ----------
print("== Binance daily metrics (OI / top-trader L-S / taker) ==", flush=True)
for sym, start_date in (("BTCUSDT", date(2020, 9, 1)), ("ETHUSDT", date(2021, 12, 1))):
    asset = sym[:3].lower()
    charts = {suf: load_existing(f"bn_{suf}_{asset}") for suf in METRIC_COLS.values()}
    day, end = start_date, date.today()
    n_fetch = n_skip = n_err = 0
    while day < end:
        ds = day.isoformat()
        if all(ds in c for c in charts.values()):
            n_skip += 1
            day += timedelta(days=1)
            continue
        r = get(f"{BZ}/data/futures/um/daily/metrics/{sym}/{sym}-metrics-{ds}.zip")
        n_fetch += 1
        if r:
            try:
                hdr, rows = csv_lines(r.content)
                if not rows:
                    raise ValueError("no rows")
                idx = {h: i for i, h in enumerate(hdr)} if hdr else \
                    {h: i for i, h in enumerate(["create_time", "symbol", "sum_open_interest",
                                                 "sum_open_interest_value", "count_toptrader_long_short_ratio",
                                                 "sum_toptrader_long_short_ratio", "count_long_short_ratio",
                                                 "sum_taker_long_short_vol_ratio"])}
                last = rows[-1].split(",")
                for col, suf in METRIC_COLS.items():
                    try:
                        charts[suf][ds] = str(float(last[idx[col]]))
                    except (ValueError, IndexError, KeyError):
                        pass
            except Exception:
                n_err += 1
        if n_fetch % 100 == 0:
            print(f"  {sym}: fetched {n_fetch}, skipped {n_skip}, err {n_err}, at {ds}", flush=True)
        time.sleep(0.04)
        day += timedelta(days=1)
    print(f"  {sym}: fetched {n_fetch}, skipped {n_skip}, err {n_err}", flush=True)
    for suf, c in charts.items():
        write(f"bn_{suf}_{asset}", c)

# ---------- 3. Binance monthly funding ----------
print("== Binance monthly funding (daily sums) ==", flush=True)
for sym in ("BTCUSDT", "ETHUSDT"):
    asset = sym[:3].lower()
    name = f"bn_funding_{asset}"
    d = load_existing(name)
    m = date(2020, 1, 1)
    end = date.today().replace(day=1)
    months = 0
    while m < end:
        ms = f"{m.year:04d}-{m.month:02d}"
        r = get(f"{BZ}/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{ms}.zip")
        months += 1
        if r:
            try:
                hdr, rows = csv_lines(r.content)
                idx = {h: i for i, h in enumerate(hdr)} if hdr else {h: i for i, h in enumerate(FUND_COLS)}
                month_sums = {}
                for line in rows:
                    parts = line.split(",")
                    # calc_time is UNIX MILLISECONDS (not a date string)
                    day = datetime.fromtimestamp(int(parts[idx["calc_time"]]) / 1000,
                                                 tz=timezone.utc).strftime("%Y-%m-%d")
                    month_sums[day] = month_sums.get(day, 0.0) + float(parts[idx["last_funding_rate"]])
                d.update({k: str(v) for k, v in month_sums.items()})
            except Exception as e:
                print(f"  {ms} parse err: {type(e).__name__}", flush=True)
        time.sleep(0.05)
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    print(f"  {sym}: {months} monthly files", flush=True)
    write(name, d)

print("BACKFILL DONE", flush=True)
