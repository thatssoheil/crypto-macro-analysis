#!/usr/bin/env python3
"""
SOL DEEP-DRAWDOWN STATE STUDY - what happened next, conditioned on where SOL sits.

The question this answers (owner, 2026-11-18): "should I accumulate SOL in the coming
months before the next leg?" An unconditional buy-and-hold multiple answers a different
question, so this measures forward returns CONDITIONED on the state we are actually in:
deep drawdown, below the 200-day, fear extreme.

States tested (each reported with sample size, episode count and the baseline):
  A  deep bear      drawdown from running ATH <= -60% AND close < 200d MA
  B  deep only      drawdown <= -60% (either side of the 200d)
  C  deep + fear    A AND Fear and Greed <= 25
  D  deep + reclaim A is false, drawdown <= -60%, close > 200d MA  (the recovery leg)
  E  no condition   every day in the same window (the baseline)

Forward horizons: 30 / 90 / 180 / 365 calendar days.

Honesty constraints that decide how to read this:
  - Daily observations OVERLAP. N is inflated; the number that matters is EPISODES
    (observations separated by more than 90 days). Both are printed.
  - SOL has exactly ONE completed deep bear (2022). Any rate here is a sample of one
    cycle plus the unresolved current one. It is a description, not a probability.
  - No costs, close-to-close, no survivorship correction.

Also printed: the CONFIRMATION COST - how far price had already travelled when the
200-day was reclaimed after each deep low. That is the price of waiting for the trend.

Stateless: prints to stdout, saves nothing.
"""
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"
HORIZONS = (30, 90, 180, 365)


def load(name, date_col="date", col="close"):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[col] if col in df.columns else df


def episodes(mask, gap_days=90):
    """Count clusters of True observations separated by more than gap_days."""
    days = mask.index[mask]
    if len(days) == 0:
        return 0
    n, last = 1, days[0]
    for d in days[1:]:
        if (d - last).days > gap_days:
            n += 1
        last = d
    return n


def fwd(px, idx, h):
    """Forward simple return over h calendar days, from each observation date."""
    out = []
    for d in idx:
        target = d + pd.Timedelta(days=h)
        if target > px.index[-1]:
            out.append(np.nan)
            continue
        p0 = float(px.asof(d))
        p1 = float(px.asof(target))
        out.append(p1 / p0 - 1 if p0 else np.nan)
    return np.array(out, dtype=float)


def report(name, mask, px, baseline_mask=None):
    idx = mask.index[mask]
    if len(idx) == 0:
        print(f"  {name:<26} no observations")
        return
    n_ep = episodes(mask)
    print(f"  {name:<26} obs {len(idx):>4}  episodes {n_ep:>2}  "
          f"first {idx[0]:%Y-%m-%d}  last {idx[-1]:%Y-%m-%d}")
    for h in HORIZONS:
        r = fwd(px, idx, h)
        r = r[~np.isnan(r)]
        if len(r) == 0:
            print(f"      {h:>3}d: no completed windows")
            continue
        pos = (r > 0).mean() * 100
        line = (f"      {h:>3}d: median {np.median(r)*100:+7.1f}%   mean {np.mean(r)*100:+8.1f}%   "
                f"positive {pos:5.1f}%   n={len(r)}")
        if baseline_mask is not None:
            b = fwd(px, baseline_mask.index[baseline_mask], h)
            b = b[~np.isnan(b)]
            if len(b):
                line += f"   | baseline median {np.median(b)*100:+7.1f}%"
        print(line)


def main():
    px = load("solusd_daily_yahoo", "ts").dropna()
    px = px[~px.index.duplicated(keep="last")].sort_index()
    fng = load("fear_greed", col="value")

    ath = px.cummax()
    dd = px / ath - 1
    ma200 = px.rolling(200).mean()
    above = px > ma200

    f = fng.reindex(px.index, method="ffill") if fng is not None else pd.Series(np.nan, index=px.index)

    states = {
        "A deep bear (<-60%, <200d)": (dd <= -0.60) & ~above & ma200.notna(),
        "B deep only (<=-60%)": (dd <= -0.60),
        "C deep + fear (F&G<=25)": (dd <= -0.60) & ~above & (f <= 25) & ma200.notna(),
        "D deep + above 200d": (dd <= -0.60) & above & ma200.notna(),
    }
    baseline = pd.Series(True, index=px.index)

    print("=" * 96)
    print(f"SOL DEEP-DRAWDOWN STATE STUDY   {px.index[0]:%Y-%m-%d} -> {px.index[-1]:%Y-%m-%d}   "
          f"({len(px)} daily closes)")
    print("=" * 96)
    print(f"now: close ${px.iloc[-1]:,.2f}  drawdown from running ATH {dd.iloc[-1]*100:+.1f}%  "
          f"200d MA ${ma200.iloc[-1]:,.2f} ({(px.iloc[-1]/ma200.iloc[-1]-1)*100:+.1f}%)  "
          f"F&G {f.iloc[-1]:.0f}")
    print(f"current state matches: " + ", ".join(k for k, m in states.items() if m.iloc[-1]))

    print("\nFORWARD RETURNS BY STATE (close to close, calendar horizons)")
    print(f"  {'baseline (all days)':<26} obs {len(px):>4}")
    for h in HORIZONS:
        r = fwd(px, px.index, h)
        r = r[~np.isnan(r)]
        print(f"      {h:>3}d: median {np.median(r)*100:+7.1f}%   mean {np.mean(r)*100:+8.1f}%   "
              f"positive {(r>0).mean()*100:5.1f}%   n={len(r)}")
    for name, mask in states.items():
        print()
        report(name, mask, px, baseline)

    # ------------------------------------------------------------------ confirmation cost
    print("\nCONFIRMATION COST - distance travelled before the 200-day was reclaimed")
    idx = px.index
    below = ~above
    episodes_started = []
    was_below = False
    for i, d in enumerate(idx):
        if below.iloc[i] and not was_below:
            start = i
            was_below = True
        elif (not below.iloc[i]) and was_below:
            low_i = int(np.argmin(px.iloc[start:i + 1].values)) + start
            episodes_started.append((idx[low_i], px.iloc[low_i], d, px.iloc[i]))
            was_below = False
    for low_d, low_p, rec_d, rec_p in episodes_started:
        if low_p <= 0:
            continue
        print(f"  low {low_d:%Y-%m-%d} ${low_p:>7,.2f}  ->  200d reclaim {rec_d:%Y-%m-%d} "
              f"${rec_p:>7,.2f}   cost of waiting {rec_p/low_p-1:+.0%}   "
              f"({(rec_d-low_d).days} days)")
    if was_below:
        low_i = int(np.argmin(px.iloc[start:].values)) + start
        print(f"  CURRENT: still below the 200d since {idx[start]:%Y-%m-%d}; low so far "
              f"{idx[low_i]:%Y-%m-%d} ${px.iloc[low_i]:,.2f}; reclaim level now "
              f"${ma200.iloc[-1]:,.2f} = {(ma200.iloc[-1]/px.iloc[low_i]-1)*100:+.0f}% above that low")

    print("\nREAD THIS AS: a description of two states, not a probability. One completed deep")
    print("bear (2022) supplies almost every observation, and the current one has no ending yet.")


if __name__ == "__main__":
    main()
