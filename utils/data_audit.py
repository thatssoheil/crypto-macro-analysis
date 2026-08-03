import pandas as pd
from pathlib import Path

DATA = Path("/home/thatssoheil/hermes-dump/forex-bot/data")

def load_h1(name):
    for p in [DATA / f"{name}_H1_MT5.csv", DATA / f"{name}_cash_H1.csv", DATA / f"{name}_H1.csv"]:
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            df = df[~df.index.duplicated()].sort_index()
            return df, p.name
    return None, None

print("=== H1 GENUINE-DATA-GAP AUDIT (weekend closes EXCLUDED) ===")
print(f"{'sym':<12}{'file':<22}{'src':>4}{'rows':>8}{'yrs':>6}{'exp_h1bars':>11}{'missing_intraweek':>19}{'cap_trunc':>11}")
print("-"*95)

# FX weekend close: Sat 00:00 UTC - Mon 00:00 UTC roughly (Fri 21:00 close)
def weekday_gaps(idx, tf):
    """Count missing intra-week bars (gaps >2xTF that don't span a weekend)."""
    if len(idx) < 2: return 0
    prev_ts = None; n = 0
    for ts in idx:
        if prev_ts is None:
            prev_ts = ts; continue
        gap = ts - prev_ts
        if gap > tf*2:
            # skip gaps that cross a weekend (prev Fri / Sat / Sun -> next Mon)
            is_weekend_cross = (prev_ts.weekday() >= 4 and ts.weekday() <= 1 and (ts.date()-prev_ts.date()).days >= 2) \
                               or prev_ts.weekday() >= 5 or ts.weekday() >= 5
            if not is_weekend_cross:
                n += 1
        prev_ts = ts
    return n

def analyze(name):
    df, fname = load_h1(name)
    if df is None: return None
    idx = df.index
    start, end = idx[0], idx[-1]
    years = (end - start).days / 365.25
    tf = pd.Timedelta(hours=1)
    # expected H1 bars: business days * 24 minus 21:00-23:00 Fri.. FX ~ open ~06:00 Mon to 21:00 Fri UTC
    # ~ 5.75 days * 24 per week -> approximate with resample count
    weeks = years*52
    exp = int(weeks * 5 * 24)  # ~5 trading days * 24h
    miss = weekday_gaps(idx, tf)
    truncated = (len(idx) >= 49990)  # hit the 50000 cap
    return name, fname, "MT5" if "MT5" in fname else "cash" if "cash" in fname else "YF", len(idx), years, exp, miss, truncated

for name in ["EURUSD","GBPUSD","XAUUSD","USDJPY","US100.cash","US500.cash","US30.cash","USOIL","US2Y"]:
    r = analyze(name)
    if r:
        print(f"{r[0]:<12}{r[1]:<22}{r[2]:>4}{r[3]:>8}{r[4]:>6.1f}{r[5]:>11}{r[6]:>19}{'*CAP*' if r[7] else '':>11}")
