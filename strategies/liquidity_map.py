#!/usr/bin/env python3
"""
LIQUIDITY MAP - modelled liquidation levels for perps, rebuilt from arithmetic.

Owner ask (2026-10-31): the Coinglass liquidation heatmap sits behind a paid API
(the endpoints answer "API key missing"). The picture is not a feed - it is a
model: positions opened over time, the margin formula, and an assumed leverage
mix, binned into a price-by-time grid. So we own the arithmetic and skip the
vendor.

Method (house conventions, see AGENTS.md):
  - Price and volume: OKX BTC-USDT-SWAP hourly candles, keyless, paginated back
    over the cohort window. USD volume comes from the candle's quote field.
  - Open interest: current aggregate, keyless, in fallback order
    edgeornet (Binance + Bybit) -> OKX -> Gate. Only the TOTAL matters here;
    the time shape comes from traded volume, so a snapshot suffices.
  - Cohorts: each hour's traded volume is the weight of the positions opened in
    that hour. Each bar spreads its mass over three entry samples (low, middle,
    high) because entries are not all at one print. Mass is multiplied across
    the PUBLISHED leverage distribution (see LEVERAGE_PROFILES) and split
    50/50 long and short, the same assumption the commercial models make.
  - Liquidation price, isolated margin:
        long  = entry * (1 - 1/L + mmr)
        short = entry * (1 + 1/L - mmr)
    mmr is the maintenance-margin rate, tiered by leverage (APPROX_MMR).
  - Cohorts decay in four tranches across COHORT_DAYS and are removed the moment
    price trades through their liquidation level after the entry bar. A level
    that was swept is gone in the picture, exactly like a live heatmap.
  - Everything is normalised to the current open interest, so cluster sizes are
    in dollars of modelled notional, not arbitrary units.

Read it as: mass ABOVE price = short liquidations (forced buying if reached),
mass BELOW price = long liquidations (forced selling if reached).

Honest limits, printed at run time:
  - The leverage mix IS the model. Two providers over the same open interest
    differ by multiples purely from this table. Published here so you can argue
    with the number instead of the picture.
  - Venue coverage is partial from this machine (Binance and Bybit endpoints are
    geo-blocked; open interest is pulled through an aggregator). Sizes are a
    floor for the whole market, shapes travel.
  - Modelled levels are not orders, not stops and not a promise of direction.

Usage:
    ./.venv/bin/python strategies/liquidity_map.py
    ./.venv/bin/python strategies/liquidity_map.py --profile retail --hours 336
    ./.venv/bin/python strategies/liquidity_map.py --calibrate
    ./.venv/bin/python strategies/liquidity_map.py --json

Stateless: prints to stdout, saves nothing.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

OKX = "https://www.okx.com"
UA = {"User-Agent": "Mozilla/5.0 (compatible; crypto-macro-analysis/liquidity_map)"}

COHORT_DAYS = 14          # how long a modelled position survives
DECAY = (1.0, 0.75, 0.5, 0.25)   # survival by quarter of life
SPLIT_LONG = 0.5          # long share of new exposure (the published assumption)
BIN_PCT = 0.001           # price bin size, 0.1 percent of spot
RANGE_PCT = 0.10          # drawn range, +/- 10 percent of spot
N_BINS = 200
ENTRY_SAMPLES = ((0.25, "low"), (0.5, "mid"), (0.25, "high"))

# Maintenance-margin rate by leverage tier. Real venues use notional tiers; we
# do not know position size per cohort, so this is a flat approximation.
APPROX_MMR = {2: 0.004, 5: 0.004, 10: 0.005, 20: 0.005, 25: 0.01, 50: 0.01, 100: 0.02}

# Leverage distributions, notional share per tier. Sum normalised in code.
LEVERAGE_PROFILES = {
    # Mixed book, the default: most notional in the 10-25 range.
    "balanced": {2: 0.09, 5: 0.19, 10: 0.27, 20: 0.22, 25: 0.15, 50: 0.08},
    # Retail-dominated: high tiers carry most of the size.
    "retail": {5: 0.11, 10: 0.18, 25: 0.24, 50: 0.22, 100: 0.25},
    # Funded desks: most size at low leverage, liquidation levels far away.
    "desk": {2: 0.23, 5: 0.32, 10: 0.25, 20: 0.12, 25: 0.06, 50: 0.02},
}


# ----------------------------------------------------------------------------- data
def _get(url, params=None, tries=3, timeout=25):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as exc:                     # network, JSON, HTTP
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"fetch failed: {url} ({last})")


def okx_candles(hours, inst="BTC-USDT-SWAP"):
    """Hourly OHLC plus USD volume, oldest first, at least `hours` bars."""
    rows, after = [], None
    while len(rows) < hours + 4:
        params = {"instId": inst, "bar": "1H", "limit": "100"}
        if after:
            params["after"] = after
        data = _get(f"{OKX}/api/v5/market/history-candles", params).get("data") or []
        if not data:
            break
        rows.extend(data)
        after = data[-1][0]
        if len(data) < 100:
            break
    if not rows:
        raise RuntimeError("no candles returned")
    df = pd.DataFrame(
        [
            {
                "ts": int(r[0]) // 1000,
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "usd_vol": float(r[7]),
            }
            for r in rows
        ]
    )
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if len(df) < hours:
        raise RuntimeError(f"only {len(df)} bars available, need {hours}")
    return df.tail(hours).reset_index(drop=True)


def open_interest(coin="BTC"):
    """Current aggregate open interest in USD, plus the label of the source."""
    try:
        j = _get(f"https://edgeornot.com/api/oi/{coin}?days=1")
        last = float(j["binance"][-1]) + float(j["bybit"][-1])
        if last > 0:
            return last, "edgeornot: Binance + Bybit"
    except Exception:
        pass
    try:
        d = _get(f"{OKX}/api/v5/rubik/stat/contracts/open-interest-volume",
                 {"ccy": coin, "period": "1H"}).get("data") or []
        if d and float(d[0][1]) > 0:
            return float(d[0][1]), "OKX (single venue)"
    except Exception:
        pass
    d = _get("https://api.gateio.ws/api/v4/futures/usdt/contract_stats",
             {"contract": f"{coin}_USDT", "interval": "1h", "limit": 2})
    return float(d[-1]["open_interest_usd"]), "Gate (single venue)"


# ---------------------------------------------------------------------------- model
def liq_levels(entries, levs, mmr, side):
    """Liquidation price for an entry, a leverage and a side (isolated margin)."""
    scale = 1.0 / levs
    if side == "long":
        mult = 1.0 - scale + mmr
    else:
        mult = 1.0 + scale - mmr
    return entries * mult


def bin_index(prices, lo, step):
    """Bin index per price, -1 when the level sits outside the drawn range."""
    raw = ((prices - lo) / step).astype(int)
    return np.where((raw >= 0) & (raw < N_BINS), raw, -1)


def build_grid(df, oi_usd, profile, cohort_hours, spot=None, full=True, null_rng=None):
    """Cohort model -> (time x price) modelled notional matrix and its pieces."""
    spot = float(df.close.iloc[-1]) if spot is None else float(spot)
    lo = spot * (1.0 - RANGE_PCT)
    step = spot * BIN_PCT

    vol = df.usd_vol.to_numpy(dtype=float)
    cap = 6.0 * np.median(vol)                        # stop one bar dominating
    weight = np.clip(vol, 0.0, cap)
    weight = weight / weight.sum()
    if null_rng is not None:
        # null model: same everything, but the link between where volume traded
        # and where the positions sit is destroyed
        weight = null_rng.permutation(weight)

    mid = (df.high.to_numpy() + df.low.to_numpy()) / 2.0
    samples = np.stack(
        [df.low.to_numpy(), mid, df.high.to_numpy()], axis=1
    )                                                  # (n, 3)
    sw = np.array([w for w, _ in ENTRY_SAMPLES])

    levs = np.array(sorted(profile), dtype=float)
    lw = np.array([profile[int(L)] for L in levs])
    lw = lw / lw.sum()
    mmr = np.array([APPROX_MMR[int(L)] for L in levs])

    n = len(df)
    # entry[n,3,1] x leverage[1,1,m] -> liquidation price per cohort, per side
    entry = samples[:, :, None]
    lng = liq_levels(entry, levs[None, None, :], mmr[None, None, :], "long")
    sht = liq_levels(entry, levs[None, None, :], mmr[None, None, :], "short")

    mass = (weight[:, None] * sw[None, :])[:, :, None] * lw[None, None, :] * oi_usd
    mass = mass * SPLIT_LONG

    # sweep tables: first hour AFTER j whose low/high reaches a bin. A position
    # opened inside bar j is not swept by bar j itself, so the search starts at
    # j+1. Bars trading beyond the drawn range are clipped to the edges, which
    # correctly counts them as reaching every bin inside.
    low_bin = np.clip(((df.low.to_numpy() - lo) / step).astype(int), 0, N_BINS - 1)
    high_bin = np.clip(((df.high.to_numpy() - lo) / step).astype(int), 0, N_BINS - 1)
    bins = np.arange(N_BINS)
    reached_low = np.vstack([low_bin[:, None] <= bins[None, :],
                             np.zeros((1, N_BINS), dtype=bool)])
    reached_high = np.vstack([high_bin[:, None] >= bins[None, :],
                              np.zeros((1, N_BINS), dtype=bool)])
    sweep_low = _next_true(reached_low)                # (n+1, bins), row j = search from j
    sweep_high = _next_true(reached_high)

    entry_idx = np.arange(n)[:, None, None]
    cohort_bins = {"long": bin_index(lng, lo, step), "short": bin_index(sht, lo, step)}
    sweeps = {"long": sweep_low, "short": sweep_high}

    def _swept_at(t, side, decay=None, include_outside=False):
        """Cohorts of a side still alive at hour t, with their bins and mass."""
        b = cohort_bins[side]
        bb = np.clip(b, 0, N_BINS - 1)
        live = (entry_idx < t) & (sweeps[side][entry_idx + 1, bb] >= t)
        if not include_outside:
            live = live & (b >= 0)
        m = mass * (1.0 if decay is None else decay)
        return bb, np.where(live, m, 0.0)

    # rescale so the survivors at the last hour sum to the real open interest
    tail_age = (n - np.arange(n)[:, None]) / max(cohort_hours / 4.0, 1e-9)
    tail_decay = np.array([DECAY[min(int(q), 3)] for q in np.clip(tail_age, 0, 3.999).ravel()])[:, None]
    survivors = sum(
        float(_swept_at(n, s, tail_decay[:, :, None], include_outside=True)[1].sum())
        for s in ("long", "short")
    )
    if survivors > 0:
        mass = mass * (oi_usd / survivors)

    matrix = np.zeros((n + 1, N_BINS))
    outside = 0.0
    for t in (range(1, n + 1) if full else (n,)):
        slope = np.clip((t - np.arange(n)) / max(cohort_hours / 4.0, 1e-9), 0, 3.999)
        decay = np.array([DECAY[int(q)] for q in slope])[:, None, None]
        in_range = 0.0
        for side in ("long", "short"):
            bb, contrib = _swept_at(t, side, decay)
            np.add.at(matrix[t], bb.ravel(), contrib.ravel())
            in_range += float(contrib.sum())
        if t == n:
            alive_total = oi_usd           # mass after rescaling to the real open interest
            outside = max(alive_total - in_range, 0.0)
    matrix[0] = 0.0

    return {
        "spot": spot,
        "lo": lo,
        "step": step,
        "bins": lo + bins * step,
        "matrix": matrix,
        "entry": entry,
        "long_px": lng,
        "short_px": sht,
        "mass": mass,
        "df": df,
        "profile": profile,
        "oi_usd": oi_usd,
        "outside": outside,
    }


def _next_true(flags):
    """For each row j and column c: first row index >= j where flags is true."""
    n = flags.shape[0]
    out = np.full(flags.shape, n, dtype=int)
    nxt = np.full(flags.shape[1], n, dtype=int)
    for j in range(n - 1, -1, -1):
        nxt = np.where(flags[j], j, nxt)
        out[j] = nxt
    return out


def key_levels(grid, top=5, merge_pct=0.004, side="both"):
    """Merge adjacent hot bins into levels and rank them by modelled notional."""
    m = grid["matrix"][-1]
    spots = grid["spot"]
    order = np.argsort(-m)
    taken = np.zeros(N_BINS, dtype=bool)
    levels = []
    for i in order:
        if m[i] <= 0 or taken[i]:
            continue
        price = grid["bins"][i]
        near = np.abs(grid["bins"] - price) <= price * merge_pct
        usd = float(m[near].sum())
        taken |= near
        levels.append(
            {
                "price": float(price),
                "dist_pct": (price / spots - 1.0) * 100.0,
                "usd": usd,
                "side": "short_liq" if price > spots else "long_liq",
            }
        )
    above = [x for x in levels if x["price"] > spots][:top]
    below = [x for x in levels if x["price"] < spots][:top]
    if side == "above":
        return above
    if side == "below":
        return below
    return above, below


def ladder(grid, band_pct=3.0):
    """Modelled notional inside a percentage band each side of spot."""
    m = grid["matrix"][-1]
    spots = grid["spot"]
    d = (grid["bins"] / spots - 1.0) * 100.0
    up = float(m[(d > 0) & (d <= band_pct)].sum())
    dn = float(m[(d < 0) & (d >= -band_pct)].sum())
    return {"within_band_up": up, "within_band_down": dn,
            "drawn_range": float(m.sum()), "outside_range": float(grid.get("outside", 0.0))}


# --------------------------------------------------------------------------- output
SHADES = " .:-=+*#%@"


def ascii_heatmap(grid, rows=28, cols=56, hours_per_col=3):
    """Compact price-by-time rendering of the modelled notional grid."""
    m = grid["matrix"][1:]                      # drop the empty pre-history row
    n = m.shape[0]
    take = min(cols * hours_per_col, n)
    keep = m[-take:]
    per = max(1, keep.shape[0] // cols)
    pooled = np.stack(
        [keep[i:i + per].max(axis=0) for i in range(0, keep.shape[0] - per + 1, per)], axis=0
    )                                           # (columns, bins)
    per_price = max(1, N_BINS // rows)
    pr = np.stack(
        [pooled[:, i:i + per_price].sum(axis=1) for i in range(0, N_BINS - per_price + 1, per_price)],
        axis=1,
    )                                           # (columns, rows)
    top = np.percentile(pr[pr > 0], 97) if (pr > 0).any() else 1.0
    idx = (np.clip(pr / max(top, 1.0), 0, 0.999) * len(SHADES)).astype(int)

    row_price = grid["bins"][np.minimum((np.arange(pr.shape[1]) + 1) * per_price, N_BINS - 1)]
    spot_row = int(np.argmin(np.abs(row_price - grid["spot"])))
    width = pr.shape[0]

    lines = [f"  intensity: {SHADES[1]}{SHADES[4]}{SHADES[7]} = thin .. dense   "
             f"column = {per}h   row = {per_price * grid['step']:,.0f} USD"]
    lines.append("  " + " " * 11 + "+" + "-" * width + "+")
    for r in range(pr.shape[1] - 1, -1, -1):
        bar = "".join(SHADES[idx[c, r]] for c in range(width))
        tag = " < spot" if r == spot_row else ""
        lines.append(f"  {row_price[r]:>10,.0f} |{bar}|{tag}")
    lines.append("  " + " " * 11 + "+" + "-" * width + "+")
    first = datetime.fromtimestamp(int(grid["df"].ts.iloc[-take]), tz=timezone.utc)
    last = datetime.fromtimestamp(int(grid["df"].ts.iloc[-1]), tz=timezone.utc)
    lines.append(f"  {'':>10}  {first:%d %b %H:%M}" + " " * max(1, width - 26) + f"{last:%d %b %H:%M} UTC")
    return "\n".join(lines)


# ----------------------------------------------------------------------- calibrate
def _hours_to_touch(arr, start, end, level, below):
    """Hours from `start` until arr trades `level`, censored at end - start."""
    seg = arr[start:end]
    hit = np.nonzero(seg <= level)[0] if below else np.nonzero(seg >= level)[0]
    return int(hit[0]) if hit.size else int(end - start)


def _two_prop_z(h1, n1, h2, n2):
    """Two-proportion z statistic, model versus null (no scipy in this repo)."""
    if not n1 or not n2:
        return None
    p1, p2 = h1 / n1, h2 / n2
    p = (h1 + h2) / (n1 + n2)
    se = (p * (1 - p) * (1 / n1 + 1 / n2)) ** 0.5
    return (p1 - p2) / se if se else None


def calibrate(coin="BTC", cal_hours=168, tol_pct=0.5, horizon=48, top=4, step_hours=3):
    """A/B test the map against a null model of itself.

    Ground truth is measured liquidation USD per hour (Gate, keyless, 41 days of
    hourly history). The control is the SAME model with the volume weights
    permuted across the window, which destroys the link between where volume
    traded and where the positions sit but keeps total mass, leverage mix, price
    range and decay identical. Anything the real map wins, it wins on location.

    A. BURST PROXIMITY. On hours in the top quartile of liquidation flow, how far
       is the hour's extreme print from the nearest shelf of each map?

    B. MAGNET. For shelves within 8 percent of spot, the share touched within the
       horizon, stratified by distance so distance cannot explain the result.
    """
    gate = _get(
        "https://api.gateio.ws/api/v4/futures/usdt/contract_stats",
        {"contract": f"{coin}_USDT", "interval": "1h", "limit": 1000},
    )
    g = pd.DataFrame(gate)
    g["ts"] = g["time"].astype(int)
    oi = g.set_index("ts")["open_interest_usd"].astype(float)
    lq = g.set_index("ts")["long_liq_usd"].astype(float)
    sq = g.set_index("ts")["short_liq_usd"].astype(float)

    df = okx_candles(min(cal_hours + COHORT_DAYS * 24 + horizon + 4, 990))
    df = df[df.ts.isin(oi.index)].reset_index(drop=True)
    if len(df) < COHORT_DAYS * 24 + horizon + 24:
        raise RuntimeError("not enough overlapping Gate and OKX history")

    lows, highs = df.low.to_numpy(), df.high.to_numpy()
    thr = {"long": float(lq.quantile(0.75)), "short": float(sq.quantile(0.75))}
    bands = ((0.0, 0.02), (0.02, 0.04), (0.04, 0.08))
    stats = {
        s: {"bursts": 0, "hit": [0, 0], "dist": [[], []], "closer": 0,
            "touch": {b: [[0, 0], [0, 0]] for b in bands}}
        for s in ("long", "short")
    }

    first = max(COHORT_DAYS * 24, len(df) - cal_hours - horizon)
    for t in range(first, len(df) - horizon - 1, step_hours):
        window = df.iloc[t - COHORT_DAYS * 24 + 1: t + 1].reset_index(drop=True)
        oi_t = float(oi.loc[df.ts.iloc[t]])
        rng = np.random.default_rng(t)
        grids = [
            build_grid(window, oi_t, LEVERAGE_PROFILES["balanced"], COHORT_DAYS * 24, full=False),
            build_grid(window, oi_t, LEVERAGE_PROFILES["balanced"], COHORT_DAYS * 24,
                       full=False, null_rng=rng),
        ]
        spots = [gr["spot"] for gr in grids]
        for side in ("long", "short"):
            st = stats[side]
            shelves = [
                key_levels(gr, top=top, side="below" if side == "long" else "above")
                for gr in grids
            ]
            if not shelves[0] or not shelves[1]:
                continue
            lv = [np.array([s["price"] for s in sh]) for sh in shelves]
            tol = spots[0] * tol_pct / 100.0
            usd = float((lq if side == "long" else sq).loc[df.ts.iloc[t + 1]])
            if usd > thr[side]:
                extreme = float(lows[t + 1] if side == "long" else highs[t + 1])
                d = [float(np.min(np.abs(x - extreme))) for x in lv]
                st["bursts"] += 1
                for i in (0, 1):
                    st["dist"][i].append(d[i])
                    st["hit"][i] += int(d[i] <= tol)
                st["closer"] += int(d[0] < d[1])
            for i, spot in enumerate(spots):
                for p in lv[i]:
                    rel = abs(p / spot - 1.0)
                    if rel > 0.08:
                        continue
                    band = next((b for b in bands if b[0] <= rel < b[1]), None)
                    if band is None:
                        continue
                    h = _hours_to_touch(lows if side == "long" else highs,
                                        t + 1, t + horizon + 1, p, below=(side == "long"))
                    st["touch"][band][i][1] += 1
                    st["touch"][band][i][0] += int(h < horizon)

    out = {"hours_tested": cal_hours, "horizon_hours": horizon,
           "tolerance_pct": tol_pct, "burst_threshold": thr,
           "control": "same model, volume weights permuted across the window"}
    for side in ("long", "short"):
        st = stats[side]
        rec = {"bursts": st["bursts"]}
        if st["bursts"]:
            rec.update({
                "burst_hit_rate_model": st["hit"][0] / st["bursts"],
                "burst_hit_rate_null": st["hit"][1] / st["bursts"],
                "median_distance_model_usd": float(np.median(st["dist"][0])),
                "median_distance_null_usd": float(np.median(st["dist"][1])),
                "model_closer_share": st["closer"] / st["bursts"],
            })
        tot = [[0, 0], [0, 0]]
        for b in bands:
            for i in (0, 1):
                tot[i][0] += st["touch"][b][i][0]
                tot[i][1] += st["touch"][b][i][1]
        rec["touch_total"] = {
            "model": tot[0][0] / tot[0][1] if tot[0][1] else None,
            "null": tot[1][0] / tot[1][1] if tot[1][1] else None,
            "n_model": tot[0][1],
            "n_null": tot[1][1],
            "z": _two_prop_z(tot[0][0], tot[0][1], tot[1][0], tot[1][1]),
        }
        rec["touch_by_distance"] = {
            f"{int(lo_*100)}-{int(hi*100)}%": {
                "model": (st["touch"][(lo_, hi)][0][0] / st["touch"][(lo_, hi)][0][1]
                          if st["touch"][(lo_, hi)][0][1] else None),
                "null": (st["touch"][(lo_, hi)][1][0] / st["touch"][(lo_, hi)][1][1]
                         if st["touch"][(lo_, hi)][1][1] else None),
                "n_model": st["touch"][(lo_, hi)][0][1],
                "n_null": st["touch"][(lo_, hi)][1][1],
            }
            for lo_, hi in bands
        }
        out[side] = rec
    return out


# ---------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Modelled liquidation map, free data only.")
    ap.add_argument("--coin", default="BTC")
    ap.add_argument("--hours", type=int, default=COHORT_DAYS * 24, help="cohort window in hours")
    ap.add_argument("--profile", default="balanced", choices=sorted(LEVERAGE_PROFILES))
    ap.add_argument("--json", action="store_true", help="machine-readable summary")
    ap.add_argument("--calibrate", action="store_true", help="walk-forward test against Gate liquidations")
    ap.add_argument("--cal-hours", type=int, default=168)
    args = ap.parse_args(argv)

    if args.calibrate:
        res = calibrate(coin=args.coin, cal_hours=args.cal_hours)
        if args.json:
            print(json.dumps(res, indent=2))
            return 0
        print("=" * 78)
        print(f"CALIBRATION  {args.coin}  walk-forward over {res['hours_tested']} h, "
              f"horizon {res['horizon_hours']} h, tolerance {res['tolerance_pct']}%")
        print(f"control: {res['control']}")
        print("=" * 78)
        print("A. liquidation bursts: how close was the hour's extreme to the nearest shelf?")
        for side in ("long", "short"):
            r = res[side]
            if not r["bursts"]:
                print(f"   {side:>5}: no bursts above threshold, skipped")
                continue
            print(f"   {side:>5}: {r['bursts']:>3} bursts   "
                  f"hit model {r['burst_hit_rate_model']*100:5.1f}% / null {r['burst_hit_rate_null']*100:5.1f}%   "
                  f"median miss {r['median_distance_model_usd']:,.0f} / {r['median_distance_null_usd']:,.0f} USD   "
                  f"model closer {r['model_closer_share']*100:.0f}%")
        print("B. magnet: share of shelves touched within the horizon")
        for side in ("long", "short"):
            t = res[side]["touch_total"]
            if not t["n_model"]:
                continue
            print(f"   {side:>5}: model {t['model']*100:5.1f}% (n={t['n_model']:>4})   "
                  f"null {t['null']*100:5.1f}% (n={t['n_null']:>4})   z={t['z']:+.2f}")
        for side in ("long", "short"):
            for band, v in res[side]["touch_by_distance"].items():
                if not v["n_model"]:
                    continue
                print(f"   {side:>5} {band:>6}: model {v['model']*100 if v['model'] is not None else float('nan'):5.1f}% "
                      f"(n={v['n_model']:>3})   null {v['null']*100 if v['null'] is not None else float('nan'):5.1f}% "
                      f"(n={v['n_null']:>3})")
        zs = [res[s]["touch_total"]["z"] for s in ("long", "short")
              if res[s]["touch_total"]["n_model"]]
        best = max([z for z in zs if z is not None], default=0.0)
        verdict = ("shelves are touched more often than the null (z > 1.6): weak but real location information"
                   if best > 1.6 else
                   "shelves do NOT beat their own null - read the map as context, not as signal")
        print(f"\n   verdict: {verdict}")
        return 0

    df = okx_candles(args.hours)
    oi_usd, oi_src = open_interest(args.coin)
    profile = LEVERAGE_PROFILES[args.profile]
    grid = build_grid(df, oi_usd, profile, args.hours)

    above, below = key_levels(grid)
    lad = ladder(grid)
    spot = grid["spot"]

    if args.json:
        print(json.dumps({
            "coin": args.coin,
            "spot": spot,
            "as_of": datetime.fromtimestamp(int(df.ts.iloc[-1]), tz=timezone.utc).isoformat(),
            "open_interest_usd": oi_usd,
            "oi_source": oi_src,
            "profile": args.profile,
            "cohort_hours": args.hours,
            "mmr_approx": {str(k): v for k, v in APPROX_MMR.items()},
            "short_levels_above": above,
            "long_levels_below": below,
            "ladder": lad,
        }, indent=2))
        return 0

    print("=" * 78)
    print(f"LIQUIDITY MAP  {args.coin}  spot {spot:,.1f}  "
          f"as of {datetime.fromtimestamp(int(df.ts.iloc[-1]), tz=timezone.utc):%Y-%m-%d %H:%M} UTC")
    print("=" * 78)
    print(f"open interest      {oi_usd/1e9:,.2f} B   ({oi_src})")
    print(f"cohort window      {args.hours} h ({args.hours/24:.0f} days), volume-weighted entries")
    print(f"leverage mix       {args.profile}: " +
          ", ".join(f"{L}x {w*100:.0f}%" for L, w in profile.items()))
    print(f"long/short split   {SPLIT_LONG*100:.0f}/{100-SPLIT_LONG*100:.0f} on new exposure (assumption)")
    print()
    print("SHORT LIQUIDATIONS ABOVE (forced buying if reached)")
    for l in above:
        print(f"   {l['price']:>10,.0f}  {l['dist_pct']:+5.2f}%   {l['usd']/1e6:8,.0f} M modelled")
    print()
    print("LONG LIQUIDATIONS BELOW (forced selling if reached)")
    for l in below:
        print(f"   {l['price']:>10,.0f}  {l['dist_pct']:+5.2f}%   {l['usd']/1e6:8,.0f} M modelled")
    print()
    print(f"within 3%: {lad['within_band_up']/1e9:,.2f} B above / {lad['within_band_down']/1e9:,.2f} B below")
    print(f"inside drawn +/-{RANGE_PCT*100:.0f}%: {lad['drawn_range']/1e9:,.2f} B   "
          f"outside (far leverage): {lad['outside_range']/1e9:,.2f} B")
    print()
    print(ascii_heatmap(grid))
    print()
    print("This is a model: no orders, no stops, no direction. The leverage mix above")
    print("is the assumption that decides where the yellow sits - argue with the table.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
