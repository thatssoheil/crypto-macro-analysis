#!/usr/bin/env python3
"""
JEV-RISK VETO VALIDATION (evidence gate, not a strategy).

What this is: the stateless evidence gate that any Jev-risk veto prototype
must pass before it touches an engine. It builds ONE candidate veto from the
five Jev-risk inputs, then audits it. It runs NO trading arm (no equity curve,
no buy-and-hold comparison, no position simulation) - only the gate.

Candidate veto definition (FIXED a priori, v0 - not tuned to the outputs):
  daily flags, all evaluated on BTC daily closes, no lookahead:
    FUND  = 7d mean Binance BTC perp funding  > 0.0003/day (crowded longs)
    VIXS  = VIX close                         > 30         (engine stress line)
    GREED = Fear & Greed value                >= 70        (engine sell line)
    VOL   = 7d realized vol (ann.)            > 100%       (vol spike)
    EXT   = BTC close > 50% above its 200d MA              (extended trend)
  VETO(day) = at least 2 of the 5 flags active AND all 5 inputs available.
  VIX / F&G / funding are forward-filled up to 7d (weekend/holiday prints);
  nothing is backfilled. Days with any input missing are uncovered: no veto.

Protocol (per the signal-promotion rule for threshold-crossing signals):
  (1) PART 1: input integrity - nulls / dupes / gaps / through-dates per input
      plus a cross-source verify (ETHUSD/ETHBTC-implied BTC vs BTCUSD).
  (2) PART 4: lead-time of veto onset vs the 2017 / 2021 / 2025 BTC tops
      (signed days = onset - top; negative = BEFORE = warning).
  (3) PART 3: false-positive scan - EVERY veto episode with forward returns;
      stats on de-flickered EPISODES (same veto clustered within a 5d cooldown
      into one episode), never on raw veto days.
  (4) Entry-delay test: each episode is scored from onset+0/+5/+10/+20d entries
      over the next 90d. TP = fwd 90d min close/entry - 1 <= -10% (the veto
      would have avoided a >10% drawdown). Precision = TP / scored episodes.
      A surviving edge is a regime marker; a collapsing edge is timing only.
  (5) Bootstrap vs matched random onsets + split by an orthogonal regime
      (price vs 200d MA at onset) to isolate incremental value.
  (6) PART 5: GATE verdict lines (cutoffs are provisional v0, stated inline).

Stateless: prints to stdout, saves nothing.
Run: ./.venv/bin/python strategies/jev_validation.py  (from repo root)
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent.parent / "data" / "macro_dataset"

COOLDOWN_D = 5
DELAYS = [0, 5, 10, 20]
FWD_D = 90
MIN_FWD_ROWS = 80
DD_THR = -0.10
N_BOOT = 2000
SEED = 7
TOPS = [
    ("2017 top", "2017-01-01", "2018-06-01"),
    ("2021 top", "2021-01-01", "2022-06-01"),
    ("2025 top", "2024-01-01", None),
]
# Provisional v0 gate cutoffs (stated, not tuned):
GATE_MIN_ELIGIBLE_D = 730
GATE_MIN_EPISODES = 10
GATE_MIN_PRECISION_D10 = 0.50
GATE_MAX_BOOT_P = 0.20
GATE_MAX_STALE_D = 21


def load(name):
    df = pd.read_csv(DATA / f"{name}.csv")
    tcol = "ts" if "ts" in df.columns else "date"
    df[tcol] = pd.to_datetime(df[tcol], utc=True)
    return df.set_index(tcol).sort_index()


def audit_one(name, col):
    df = load(name)
    s = df[col]
    idx = df.index
    nulls = int(df.isnull().sum().sum())
    dupes = int(idx.duplicated().sum())
    gaps = idx.to_series().diff().dt.total_seconds().div(86400).dropna()
    maxgap = float(gaps.max()) if len(gaps) else 0.0
    return {
        "name": name, "rows": len(df),
        "first": idx[0].date(), "last": idx[-1].date(),
        "nulls": nulls, "dupes": dupes, "maxgap_d": maxgap,
    }


print("=" * 70)
print("PART 1: JEV-RISK INPUT INTEGRITY (nulls / dupes / gaps / through-dates)")
print("=" * 70)
specs = [
    ("btcusd_daily_bitstamp", "close"),   # base for 7d vol + MA distance
    ("bn_funding_btc", "value"),
    ("vix", "close"),
    ("fear_greed", "value"),
]
aud = {}
for name, col in specs:
    a = audit_one(name, col)
    aud[name] = a
    flag = "OK" if (a["nulls"] == 0 and a["dupes"] == 0 and a["maxgap_d"] <= 10) else "CHECK"
    print(f"  {name:24s} rows={a['rows']:>5} {a['first']} -> {a['last']} "
          f"nulls={a['nulls']} dupes={a['dupes']} maxgap={a['maxgap_d']:.0f}d {flag}")
print("  (7d vol + MA distance derive from btcusd_daily_bitstamp; no extra file.)")

# Range sanity on latest values
btc_df = load("btcusd_daily_bitstamp")
fund_df = load("bn_funding_btc")
vix_df = load("vix")
fng_df = load("fear_greed")
print(f"  sanity: VIX latest {vix_df['close'].iloc[-1]:.1f} (band 5-80), "
      f"F&G latest {int(fng_df['value'].iloc[-1])} (band 0-100), "
      f"funding latest {fund_df['value'].iloc[-1]:+.6f}/day (|x| < 0.05)")

# Cross-source verify: ETHUSD/ETHBTC-implied BTC vs direct BTCUSD (independent CSVs)
try:
    ethusd = load("ethusd_daily_bitstamp")["close"]
    ethbtc = load("ethbtc_daily_bitstamp")["close"]
    px_direct = btc_df["close"]
    common = ethusd.index.intersection(ethbtc.index).intersection(px_direct.index)
    implied = (ethusd.loc[common] / ethbtc.loc[common]).replace([np.inf, -np.inf], np.nan).dropna()
    cc = common.intersection(implied.index)
    diff = (implied.loc[cc] / px_direct.loc[cc] - 1).abs() * 100
    print(f"  x-verify ETHUSD/ETHBTC-implied BTC vs BTCUSD: n={len(diff)} "
          f"median|diff|={diff.median():.3f}% max={diff.max():.2f}% "
          f"days>1%={int((diff > 1.0).sum())} "
          f"{'OK' if diff.median() < 0.5 else 'CHECK'}")
except Exception as e:
    print(f"  x-verify BTC cross-source: SKIPPED ({e})")

# ---- build the panel ----
px = btc_df["close"]
ma200 = px.rolling(200).mean()
dist = px / ma200 - 1
vol7 = np.log(px / px.shift(1)).rolling(7).std() * np.sqrt(365) * 100
fund7 = fund_df["value"].reindex(px.index).ffill(limit=7)
vix = vix_df["close"].reindex(px.index).ffill(limit=7)
fng = fng_df["value"].reindex(px.index).ffill(limit=7)
panel = pd.DataFrame({"px": px, "ma200": ma200, "dist": dist, "vol7": vol7,
                      "fund7": fund7, "vix": vix, "fng": fng})
eligible = panel.notna().all(axis=1)
print(f"  veto-eligible panel: {eligible.sum()} days, "
      f"{panel.index[eligible].min().date()} -> {panel.index[eligible].max().date()} "
      f"(intersection of all 5 inputs; funding floor binds the start)")

# ---- veto flags ----
flags = pd.DataFrame({
    "FUND": panel["fund7"] > 0.0003,
    "VIXS": panel["vix"] > 30,
    "GREED": panel["fng"] >= 70,
    "VOL": panel["vol7"] > 100,
    "EXT": panel["dist"] > 0.50,
})
flags = flags & eligible.values[:, None]
nflags = flags.sum(axis=1)
veto = (nflags >= 2) & eligible
print("\n  flag-day counts (eligible panel only):")
for c in flags.columns:
    print(f"    {c:6s} {int(flags[c].sum()):>5d} days")
print(f"    VETO(>=2 flags) {int(veto.sum())} days")

# ---- de-flicker: cluster veto days within 5d cooldown into episodes ----
vdates = veto[veto].index
episodes = []
if len(vdates):
    start = prev = vdates[0]
    for d in vdates[1:]:
        if (d - prev).days > COOLDOWN_D:
            episodes.append((start, prev))
            start = d
        prev = d
    episodes.append((start, prev))
onsets = pd.DatetimeIndex([s for s, _ in episodes])
print(f"  veto episodes (5d cooldown): {len(episodes)} "
      f"from {int(veto.sum())} raw veto days")
print("=" * 70)
print("PART 2: VETO EPISODES (onset, price, active flags)")
print("=" * 70)
for s, e in episodes:
    fl = "+".join([c for c in flags.columns if flags.loc[s, c]])
    ndays = (e - s).days + 1
    print(f"  onset {s.date()} px ${panel.loc[s, 'px']:,.0f} "
          f"flags {fl} nflags={int(nflags.loc[s])} span {ndays}d")


def score_from(entry_date):
    """(entry_px, minDD90, ret90) from first BTC close at/after entry_date."""
    pos = px.index.searchsorted(entry_date)
    if pos >= len(px):
        return None
    epx = float(px.iloc[pos])
    edate = px.index[pos]
    fwd = px.loc[edate:edate + pd.Timedelta(days=FWD_D)]
    if len(fwd) < MIN_FWD_ROWS or (fwd.index[-1] - edate).days < MIN_FWD_ROWS:
        return None
    return epx, float(fwd.min() / epx - 1), float(fwd.iloc[-1] / epx - 1)


print("=" * 70)
print("PART 3: FALSE-POSITIVE SCAN (every episode; TP = fwd90 min <= -10%)")
print("=" * 70)
ep_rows = []
for s, _ in episodes:
    r = {"onset": s, "px": float(panel.loc[s, "px"]),
         "above_ma": bool(panel.loc[s, "px"] >= panel.loc[s, "ma200"])}
    for k in DELAYS:
        sc = score_from(s + pd.Timedelta(days=k))
        if sc is None:
            r[k] = None
        else:
            _, mindd, ret = sc
            r[k] = (mindd, ret, mindd <= DD_THR)
    ep_rows.append(r)
for r in ep_rows:
    cells = []
    for k in DELAYS:
        v = r[k]
        cells.append("skip" if v is None else f"{v[0] * 100:+.1f}% {'TP' if v[2] else 'FP'}")
    print(f"  {r['onset'].date()} px ${r['px']:,.0f} | " +
          " | ".join(f"+{k}d {c}" for k, c in zip(DELAYS, cells)))

print("\n  --- precision table (scored episodes only; trailing edge skipped) ---")
prec = {}
for k in DELAYS:
    scored = [r for r in ep_rows if r[k] is not None]
    tp = sum(1 for r in scored if r[k][2])
    fp = len(scored) - tp
    skipped = len(ep_rows) - len(scored)
    p = tp / len(scored) if scored else float("nan")
    prec[k] = p
    print(f"  entry +{k:>2d}d: n={len(scored):>3d} TP={tp:>3d} FP={fp:>3d} "
          f"skipped={skipped:>2d} precision={p * 100:.1f}%")
print("  --- median fwd90 return by entry delay ---")
for k in DELAYS:
    rets = [r[k][1] * 100 for r in ep_rows if r[k] is not None]
    print(f"  entry +{k:>2d}d: median fwd90 {float(np.median(rets)):+.1f}% (n={len(rets)})")

# Bootstrap vs matched random onsets (delay +10d, the gate delay)
rng = np.random.default_rng(SEED)
elig_dates = panel.index[eligible]
pool = []
for d in elig_dates:
    sc = score_from(d + pd.Timedelta(days=10))
    if sc is not None:
        pool.append(sc[1] <= DD_THR)
pool = np.array(pool)
obs = prec[10]
n_scored_10 = sum(1 for r in ep_rows if r[10] is not None)
ge = 0
if len(pool) and n_scored_10:
    draws = rng.integers(0, len(pool), size=(N_BOOT, n_scored_10))
    boot = pool[draws].mean(axis=1)
    ge = int((boot >= obs).sum())
    pval = (ge + 1) / (N_BOOT + 1)
    print(f"\n  bootstrap (+10d, {N_BOOT} draws of n={n_scored_10} random eligible onsets, "
          f"seed {SEED}):")
    print(f"    random-onset precision mean {boot.mean() * 100:.1f}% "
          f"p95 {np.quantile(boot, 0.95) * 100:.1f}% | veto {obs * 100:.1f}% "
          f"| p(one-sided)={pval:.4f}")
else:
    pval = float("nan")
    print("\n  bootstrap: SKIPPED (empty pool)")

# Split by orthogonal regime: price vs 200d MA at onset (delay +10d)
print("\n  --- split by orthogonal regime at onset: price vs 200d MA (+10d) ---")
for lab, grp in [("above 200d MA", [r for r in ep_rows if r["above_ma"]]),
                 ("below 200d MA", [r for r in ep_rows if not r["above_ma"]])]:
    sc = [r for r in grp if r[10] is not None]
    tp = sum(1 for r in sc if r[10][2])
    p = tp / len(sc) * 100 if sc else float("nan")
    print(f"  {lab:14s}: n={len(sc):>3d} TP={tp:>3d} precision={p:.1f}%")

print("=" * 70)
print("PART 4: LEAD-TIME OF VETO ONSET vs CYCLE TOPS (days = onset - top)")
print("=" * 70)


def get_top(lo, hi):
    # tz-aware bounds on both sides (pandas 3.x rejects mixed slicing)
    lo_t = pd.Timestamp(lo, tz="UTC")
    hi_t = pd.Timestamp(hi, tz="UTC") if hi else px.index.max()
    win = px.loc[lo_t:hi_t]
    td = win.idxmax()
    return td, float(win.max()), td == win.index[-1]


tops_computed = []
panel_start = panel.index[eligible].min() if eligible.any() else None
for label, lo, hi in TOPS:
    top_date, top_px, at_edge = get_top(lo, hi)
    tops_computed.append((label, top_date))
    edge = " (ATH at window edge - top UNCONFIRMED)" if at_edge else ""
    print(f"\n  {label}: BTC ATH {top_date.date()} (${top_px:,.0f}){edge}")
    if panel_start is not None and top_date < panel_start:
        print(f"    NO-COVERAGE: top predates veto panel start {panel_start.date()} "
              f"(funding floor 2020-01-01)")
        continue
    past = onsets[onsets <= top_date]
    fut = onsets[onsets >= top_date]
    if len(past):
        d = past.max()
        lag = (d - top_date).days
        print(f"    nearest onset at/before top: {d.date()} ({lag:+d}d = "
              f"{-lag}d BEFORE top, BTC ${panel.loc[d, 'px']:,.0f})")
    else:
        print("    nearest onset at/before top: none in panel")
    if len(fut):
        d = fut.min()
        lag = (d - top_date).days
        print(f"    first onset at/after top:    {d.date()} ({lag:+d}d = "
              f"{lag}d AFTER top, BTC ${panel.loc[d, 'px']:,.0f})")
    else:
        print("    first onset at/after top: none in panel")

print("=" * 70)
print("PART 5: JEV GATE VERDICT (provisional v0 cutoffs - stated above)")
print("=" * 70)
btc_last = btc_df.index.max().date()
checks = []
checks.append(("coverage_days", int(eligible.sum()) >= GATE_MIN_ELIGIBLE_D,
               f"{int(eligible.sum())} eligible days (need >={GATE_MIN_ELIGIBLE_D})"))
checks.append(("n_episodes", len(episodes) >= GATE_MIN_EPISODES,
               f"{len(episodes)} episodes (need >={GATE_MIN_EPISODES})"))
p10 = prec.get(10, float("nan"))
checks.append(("precision_+10d", bool(p10 >= GATE_MIN_PRECISION_D10),
               f"{p10 * 100:.1f}% (need >={GATE_MIN_PRECISION_D10 * 100:.0f}%)"))
checks.append(("bootstrap_edge", bool(pval < GATE_MAX_BOOT_P),
               f"p={pval:.4f} (need <{GATE_MAX_BOOT_P:.2f} vs random onsets)"))
warns = 0
for label, td in tops_computed:
    if panel_start is not None and td >= panel_start and (onsets <= td).any():
        warns += 1
checks.append(("pre_top_warning", warns >= 1,
               f"{warns} covered tops with a pre-top onset (need >=1)"))
max_stale = 0
for name in ["bn_funding_btc", "vix", "fear_greed"]:
    last = audit_one(name, "value" if name != "vix" else "close")["last"]
    max_stale = max(max_stale, (btc_last - last).days)
checks.append(("freshness", max_stale <= GATE_MAX_STALE_D,
               f"max input lag vs BTC through-date {max_stale}d (need <={GATE_MAX_STALE_D}d)"))
allpass = True
for nm, ok, detail in checks:
    allpass &= bool(ok)
    print(f"  GATE {nm:16s} {'PASS' if ok else 'FAIL'} - {detail}")
print(f"\n  JEV GATE: {'PASS' if allpass else 'FAIL'} - "
      f"veto panel {panel.index[eligible].min().date()} -> "
      f"{panel.index[eligible].max().date()}, {len(episodes)} episodes, "
      f"precision@+10d {p10 * 100:.1f}%")
print("  (No trading arm was built or run - this file is evidence only.)")
