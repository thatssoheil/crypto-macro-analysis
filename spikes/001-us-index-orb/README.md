# Spike 001 — US Index ORB / open-drive (D1 proxy)

## Question
Given long US index D1 proxies, when trade open gap/open-drive (known at open) → exit close same day, then OOS Sharpe ≥ 0.8 and DD > -25%?

## Verdict: VALIDATED (proxy) — promote carefully

### What worked
- **US30** OOS 2019–22 (no loss-clip): Sharpe **~3.9**, DD **~-7.7%**, ~695 trades
- **US30** holdout 2023+: Sharpe **~1.9**, DD **~-12%**
- **US500** OOS strong; holdout **weak** (Sharpe ~0.25–0.4) → single-name fragility
- **US100** weak / invalidated on holdout
- Equal-weight OOS portfolio still strong on proxy data
- Edge family: **open-to-close direction after gap/drive**, not FX H1 noise

### What didn't
- US100 failed holdout
- US500 holdout decay — do not trade US500 alone on this rule
- D1 open ≠ true 09:30–09:45 ORB (needs M15 FTMO)
- Yahoo cash index ≠ FTMO CFD (spread, commission, financing, halt rules)

### Surprises
- No-clip still huge Sharpe vs buy-hold OOS (BH US30 OOS Sharpe ~0.5). Effect is large enough to survive cost stress in sample — **must re-verify on FTMO M15/H1 CSV before challenge**.

### Recommendation for real build
1. Primary sleeve: **US30 open-drive / gap** (FTMO symbol name from ExportSymbols)
2. Optional: small US500 weight only if FTMO costs OK; skip US100 for now
3. Next spike: **M15 true ORB** on FTMO export (09:30–09:45 ET range break)
4. Wire FTMORules + 0.5–1% risk + Carver vol target 10–12%
5. Demo 8 weeks before challenge

### Run
```bash
cd /home/thatssoheil/hermes-dump/forex-bot && source .venv/bin/activate
python utils/yahoo_fetch.py --interval 1d --period 20y
python spikes/001-us-index-orb/main.py
```

### Sanity
- Buy-hold US30 2019–22: Sharpe ~0.5, DD ~-37%
- Strategy OOS: much higher Sharpe, much lower DD on proxy
- Still treat as **hypothesis until FTMO tick/M15 confirms**
