#!/usr/bin/env python3
"""JEV WALK-FORWARD TRADER - the literal test the owner asked for.

At each decision date in a picked historical snippet, ask Jev (the real
router: jev_decide triage in front of the tier ladder) for a futures
position using ONLY data known at that date. Jev never sees the future.
We then score its call against the realized forward move we already have.

Repeat across snippets of many regimes; if the hit rate and net return
hold across snippets, it works for the price ahead. If they do not, it
does not.

Requires the Hermes dev clone on PYTHONPATH (credential pool auth):
  cd /root/hermes-projects/crypto-macro-analysis
  PYTHONPATH=/root/hermes-projects/hermes-agent-dev:/root/hermes-dump/jev-router \
    .venv/bin/python strategies/jev_walkforward.py --pilot
  ... --all        # every snippet
  ... --log-only   # re-evaluate a saved log, zero model calls

Raw decisions are appended to data/jev_decisions/decisions.jsonl so a
re-run is free and auditable. Results print to stdout (stateless).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data" / "macro_dataset"
LOGDIR = ROOT / "data" / "jev_decisions"
LOGFILE = LOGDIR / "decisions.jsonl"

FEE_BP_SIDE = 5.0      # taker, per side (10 bp round trip)
MM = 0.005             # maintenance margin rate
START_CAP = 10_000.0
MAX_LEV = 10.0

# regime snapshots: (name, start, end)
SNIPPETS = [
    ("covid_crash_2020", "2020-02-01", "2020-05-01"),
    ("bull_2020", "2020-09-01", "2021-01-01"),
    ("top_2021", "2021-10-01", "2022-02-01"),
    ("bear_2022", "2022-04-01", "2022-10-01"),
    ("recovery_2023", "2023-01-01", "2023-07-01"),
    ("bull_2024", "2024-02-01", "2024-08-01"),
    ("top_2025", "2025-09-01", "2026-01-01"),
    ("range_2026", "2026-03-01", "2026-09-01"),
]


def load_series(name, date_col="date", col="value"):
    df = pd.read_csv(DATA / f"{name}.csv")
    df[date_col] = pd.to_datetime(df[date_col], utc=True, errors="coerce")
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
    s = pd.to_numeric(df[col], errors="coerce")
    return s[~s.index.duplicated(keep="last")]


def load_prices():
    df = pd.read_csv(DATA / "btcusd_daily_bitstamp.csv")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()
    return df[["open", "high", "low", "close"]].astype(float)


def build_features():
    px = load_prices()
    close = px["close"]
    f = pd.DataFrame(index=px.index)
    f["close"] = close
    f["high"] = px["high"]
    f["low"] = px["low"]
    f["ma200"] = close.rolling(200).mean()
    f["dist200"] = close / f["ma200"] - 1
    f["ret30"] = close / close.shift(30) - 1
    f["ret7"] = close / close.shift(7) - 1
    ret1 = close.pct_change()
    f["rv7"] = ret1.rolling(7).std() * np.sqrt(365)
    f["ath_ratio"] = close / close.cummax() - 1

    def align(s, name):
        return s.reindex(f.index, method="ffill")

    f["funding7"] = align(load_series("bn_funding_btc"), "funding").rolling(7).mean()
    f["fng"] = align(load_series("fear_greed"), "fng")
    f["dvol"] = align(load_series("dvol_btc"), "dvol")
    f["lsr"] = align(load_series("bn_lsr_btc"), "lsr")
    oi = align(load_series("bn_oi_btc"), "oi")
    f["oi_chg7"] = oi / oi.shift(7) - 1
    return f.dropna(subset=["ma200", "rv7"])


def _f(v, fmt="{:.0f}", suffix=""):
    try:
        if v is None or np.isnan(float(v)):
            return "unavailable"
    except (TypeError, ValueError):
        return "unavailable"
    return (fmt.format(float(v)) + suffix)


def context_block(row, prev=None):
    lines = [
        f"date: {row.name.date()}",
        f"btc_close_usd: {_f(row['close'])}",
        f"vs_200d_average: {_f(row['dist200']*100, '{:+.1f}', ' percent')}",
        f"30d_return: {_f(row['ret30']*100, '{:+.1f}', ' percent')}",
        f"7d_return: {_f(row['ret7']*100, '{:+.1f}', ' percent')}",
        f"7d_realized_vol_annualized: {_f(row['rv7']*100, '{:.0f}', ' percent')}",
        f"drawdown_from_all_time_high: {_f(row['ath_ratio']*100, '{:+.1f}', ' percent')}",
        f"funding_daily_rate_7d_avg: {_f(row['funding7']*100, '{:+.4f}', ' percent per day')}",
        f"fear_greed_index: {_f(row['fng'])}",
        f"implied_vol_dvol: {_f(row['dvol'])}",
        f"top_trader_long_short_ratio: {_f(row['lsr'], '{:.2f}')}",
        f"open_interest_7d_change: {_f(row['oi_chg7']*100, '{:+.1f}', ' percent')}",
    ]
    if prev:
        lines.append(
            f"your_last_call: {prev['action']} at {prev['leverage']}x on "
            f"{prev['date']}, its realized result was "
            f"{prev['outcome_pct']:+.2f} percent over {prev['horizon_days']} days")
    return "\n".join(lines)


PROMPT_TEMPLATE = """You are a futures risk taker on BTC perpetual futures. You must
decide ONE position to hold for the next {horizon} days. You cannot see the
future. Decide from the market state below only.

Capital: {cap} usd. Risk budget per trade: 1 to 2 percent of capital.
Leverage range: 0 to {maxlev}x notional (0 means stay flat).
A round trip costs 10 basis points in fees, and long positions pay funding
daily. High leverage is liquidated by a wick of roughly (1 divided by
leverage) percent.

Market state:
{ctx}

Answer with ONLY a JSON object, no prose, in exactly this shape:
{{"action": "long" or "short" or "flat", "leverage": <number 0-{maxlev}>, "confidence": <0.0-1.0>, "reason": "<under 20 words>"}}"""


def parse_decision(text):
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        d = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    action = str(d.get("action", "")).lower().strip()
    if action not in ("long", "short", "flat"):
        return None
    try:
        lev = float(d.get("leverage", 0))
    except (TypeError, ValueError):
        return None
    lev = max(0.0, min(MAX_LEV, lev))
    if action == "flat":
        lev = 0.0
    try:
        conf = float(d.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    return {"action": action, "leverage": lev,
            "confidence": max(0.0, min(1.0, conf)),
            "reason": str(d.get("reason", ""))[:120]}


def simulate(feats, date, action, lev, horizon):
    """Forward outcome of the decision, using data the model did not see."""
    idx = feats.index
    pos = idx.get_loc(date)
    end = pos + horizon
    if end >= len(idx):
        return None
    entry = feats["close"].iloc[pos]
    exit_ = feats["close"].iloc[end]
    ret = exit_ / entry - 1
    if action == "short":
        ret = -ret
    if action == "flat" or lev == 0:
        return {"gross_pct": 0.0, "net_pct": 0.0, "equity_mult": 1.0,
                "liq": False, "entry": entry, "exit": exit_}

    # liquidation: adverse move of (1/lev - mm) wipes the isolated position
    window = feats.iloc[pos + 1:end + 1]
    if action == "long":
        worst = window["low"].min()
        adverse = entry / worst - 1
    else:
        worst = window["high"].max()
        adverse = worst / entry - 1
    ruin = 1.0 / lev - MM
    if adverse >= ruin:
        return {"gross_pct": -100.0, "net_pct": -100.0, "equity_mult": 0.0,
                "liq": True, "entry": entry, "exit": exit_}

    gross = lev * ret
    fees = 2 * (FEE_BP_SIDE / 1e4) * lev
    days = max(1, (idx[end] - idx[pos]).days)
    fund_rate = feats["funding7"].iloc[pos]
    funding = 0.0
    if not np.isnan(fund_rate):
        funding = fund_rate * days * lev * (1 if action == "long" else -1)
    net = gross - fees - funding
    return {"gross_pct": gross * 100, "net_pct": net * 100,
            "equity_mult": max(0.0, 1.0 + net), "liq": False,
            "entry": entry, "exit": exit_}


def ask_jev(row, prev, horizon):
    from jev_opencode_bundle import route_and_run
    ctx = context_block(row, prev)
    prompt = PROMPT_TEMPLATE.format(horizon=horizon, cap=START_CAP,
                                    maxlev=MAX_LEV, ctx=ctx)
    task = (f"Decide the BTC futures position to hold for the next {horizon} days "
            f"with capital at risk. This is a high stakes trading decision; a wrong "
            f"call loses real money.")
    res = route_and_run(task=task, prompt=prompt)
    write_triage_ledger(res, task, row)
    return res, prompt


def write_triage_ledger(res, task, row):
    """Audit every triage call in the router's own shadow-log shape.

    The triage posts raw HTTP (urllib) inside jev_local_router, so it never
    reaches Hermes token accounting; and route_and_run does not write
    shadow-log.jsonl. Without this line the calls are invisible. This is
    the ledger that makes consumption auditable.
    """
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "task": task[:200],
            "tier": res.get("tier"),
            "reason": res.get("reason"),
            "source": res.get("source"),
            "model": res.get("model"),
            "provider": res.get("provider"),
            "executed": res.get("executed"),
            "context_date": str(row.name.date()),
            "notes": res.get("notes"),
        }
        with (LOGDIR / "triage-ledger.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def run(args):
    feats = build_features()
    LOGDIR.mkdir(parents=True, exist_ok=True)
    existing = []
    if LOGFILE.exists():
        existing = [json.loads(l) for l in LOGFILE.read_text().splitlines() if l.strip()]
    seen = {(r["snippet"], r["date"]) for r in existing}
    all_rows = list(existing)

    snippets = SNIPPETS[:1] if args.pilot else SNIPPETS
    if args.snippet:
        snippets = [s for s in SNIPPETS if s[0] == args.snippet]
    if not args.log_only:
        for name, start, end in snippets:
            lo = pd.Timestamp(start, tz="UTC")
            hi = pd.Timestamp(end, tz="UTC")
            window = feats.loc[(feats.index >= lo) & (feats.index <= hi)]
            dates = window.index[::args.cadence]
            prev = None
            for d in dates:
                key = (name, str(d.date()))
                if key in seen:
                    continue
                row = feats.loc[d]
                if row[["close", "ma200", "rv7"]].isna().any():
                    continue
                try:
                    res, prompt = ask_jev(row, prev, args.cadence)
                except Exception as exc:
                    print(f"  WARN {name} {d.date()}: router failed: {exc}")
                    continue
                dec = parse_decision(res.get("output"))
                rec = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "snippet": name, "date": str(d.date()),
                    "horizon_days": args.cadence,
                    "tier": res.get("tier"), "reason": res.get("reason"),
                    "model": res.get("model"), "executed": res.get("executed"),
                    "raw": (res.get("output") or "")[:400],
                    "decision": dec,
                }
                if dec is None:
                    print(f"  WARN {name} {d.date()}: unparseable: {(res.get('output') or '')[:80]!r}")
                    all_rows.append(rec)
                    with LOGFILE.open("a") as f:
                        f.write(json.dumps(rec) + "\n")
                    continue
                out = simulate(feats, d, dec["action"], dec["leverage"], args.cadence)
                if out is None:
                    continue
                rec["outcome_pct"] = out["net_pct"]
                rec["liq"] = out["liq"]
                all_rows.append(rec)
                with LOGFILE.open("a") as f:
                    f.write(json.dumps(rec) + "\n")
                prev = {"action": dec["action"], "leverage": dec["leverage"],
                        "date": str(d.date()), "outcome_pct": out["net_pct"],
                        "horizon_days": args.cadence}
                print(f"  {name} {d.date()} tier={res.get('tier')} "
                      f"{dec['action']} {dec['leverage']}x -> {out['net_pct']:+.2f}%")

    report(all_rows, feats, args)


def report(rows, feats, args):
    scored = [r for r in rows if r.get("decision") and "outcome_pct" in r]
    print("\n=== JEV WALK-FORWARD RESULTS ===")
    print(f"decisions logged: {len(rows)} | scored: {len(scored)} | "
          f"horizon: {args.cadence} days | fee {FEE_BP_SIDE} bp/side")
    if not scored:
        print("no scored decisions yet")
        return

    per_snip = {}
    for r in scored:
        per_snip.setdefault(r["snippet"], []).append(r)

    print(f"\n{'snippet':22} {'n':>3} {'net%':>8} {'hit%':>6} "
          f"{'avgLev':>7} {'liq':>4} {'BH%':>8}")
    tot_mult = 1.0
    for name, rs in per_snip.items():
        nets = [r["outcome_pct"] for r in rs]
        wins = [r for r in rs if r["outcome_pct"] > 0]
        levs = [r["decision"]["leverage"] for r in rs]
        liqs = sum(1 for r in rs if r.get("liq"))
        mult = 1.0
        for r in rs:
            mult *= max(0.0, 1 + r["outcome_pct"] / 100)
        tot_mult *= mult
        # buy and hold over the same windows
        bh = 1.0
        for r in rs:
            d = pd.Timestamp(r["date"], tz="UTC")
            pos = feats.index.get_loc(d)
            end = pos + r["horizon_days"]
            if end < len(feats):
                bh *= feats["close"].iloc[end] / feats["close"].iloc[pos]
        print(f"{name:22} {len(rs):>3} {np.mean(nets):>+8.2f} "
              f"{100*len(wins)/len(rs):>6.1f} {np.mean(levs):>7.2f} {liqs:>4} "
              f"{(bh-1)*100:>+8.1f}")

    nets = [r["outcome_pct"] for r in scored]
    levs = [r["decision"]["leverage"] for r in scored]
    liqs = sum(1 for r in scored if r.get("liq"))
    print(f"\noverall: n={len(scored)} mean net {np.mean(nets):+.2f}% "
          f"median {np.median(nets):+.2f}% hit {100*sum(1 for n in nets if n>0)/len(nets):.1f}% "
          f"avg lev {np.mean(levs):.2f}x liqs {liqs} compound {tot_mult:.2f}x")

    # random-direction baseline with the same leverage and windows
    rng = np.random.default_rng(7)
    rand_nets = []
    for r in scored:
        d = pd.Timestamp(r["date"], tz="UTC")
        pos = feats.index.get_loc(d)
        end = pos + r["horizon_days"]
        if end >= len(feats):
            continue
        ret = feats["close"].iloc[end] / feats["close"].iloc[pos] - 1
        lev = r["decision"]["leverage"]
        if lev == 0:
            rand_nets.append(0.0)
            continue
        sign = 1 if rng.random() < 0.5 else -1
        rand_nets.append(100 * (lev * sign * ret - 2 * FEE_BP_SIDE / 1e4 * lev))
    if rand_nets:
        print(f"random-direction baseline (same leverage): mean net "
              f"{np.mean(rand_nets):+.2f}%")

    acts = {}
    for r in scored:
        acts[r["decision"]["action"]] = acts.get(r["decision"]["action"], 0) + 1
    print(f"action mix: {acts}")
    tiers = {}
    for r in scored:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    print(f"jev tier mix: {tiers}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true", help="first snippet only")
    ap.add_argument("--all", action="store_true", help="every snippet")
    ap.add_argument("--snippet", type=str, default=None)
    ap.add_argument("--cadence", type=int, default=5, help="decision + hold days")
    ap.add_argument("--log-only", action="store_true",
                    help="re-evaluate saved log, zero model calls")
    run(ap.parse_args())
