#!/usr/bin/env python3
"""
AutoTSMOM v2 brain — USDJPY Asian session + XAUUSD Donchian breakout.
CRON SCHEDULE:
  23:00 UTC Sun-Thu: AsianSession_Open (USDJPY entry + XAUUSD update)
  07:00 UTC Mon-Fri: AsianSession_Close (USDJPY close + XAUUSD update)
  */4h Mon-Fri:      Donchian_Check (XAUUSD signal monitoring)

ALL TIMES IN UTC. Data converted to UTC on load.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import csv
import sys
import json
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────
# ALL HOURS IN UTC
SERVER_OFFSET = 2  # FTMO server is UTC+2

ASIAN_CONFIG = {
    "symbol": "USDJPY",
    "pre_hours": 4,
    "session_open": 23,     # 23:00 UTC = 01:00 server (next day)
    "session_close": 7,     # 07:00 UTC = 09:00 server
    "atr_mult": 0.3,
    "rr": 2.0,
    "risk_pct": 1.0,
}

DONCHIAN_CONFIG = {
    "symbol": "XAUUSD",
    "lookback": 55,
    "rr": 1.5,
    "risk_pct": 1.0,
}

MT5_COMMON = Path("/home/thatssoheil/.mt5/drive_c/users/thatssoheil/AppData/Roaming/MetaQuotes/Terminal/Common/Files")
STATE_FILE = MT5_COMMON / "mt5_state.csv"
TARGET_FILE = MT5_COMMON / "mt5_targets.csv"
CONFIG_FILE = MT5_COMMON / "mt5_config.json"

DAILY_LOSS_LIMIT = 0.045
TOTAL_DD_LIMIT = 0.095
PROFIT_TARGET_P1 = 0.10

H1_DATA_DIR = Path("/home/thatssoheil/hermes-dump/forex-bot/data")

# ── FTMO State ──────────────────────────────────────────────
def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def init_ftmo_tracking(equity):
    cfg = load_config()
    if "initial_balance" not in cfg:
        cfg["initial_balance"] = equity
        cfg["day_start_equity"] = equity
        cfg["day_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cfg["halted"] = False
        save_config(cfg)
        print(f"FTMO: Initialized. Balance: ${equity:.2f}")
    return cfg

def update_day_start(cfg, equity):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if cfg.get("day_date") != today:
        cfg["day_start_equity"] = equity
        cfg["day_date"] = today
        save_config(cfg)

def check_ftmo_rules(cfg, equity):
    initial = cfg.get("initial_balance", equity)
    day_start = cfg.get("day_start_equity", equity)
    if cfg.get("halted"):
        return False, "HALTED"
    daily_pct = (equity - day_start) / day_start if day_start else 0
    if daily_pct < -DAILY_LOSS_LIMIT:
        return False, f"DAILY LOSS {daily_pct*100:.1f}%"
    total_dd = (initial - equity) / initial if initial else 0
    if total_dd > TOTAL_DD_LIMIT:
        return False, f"TOTAL DD {total_dd*100:.1f}%"
    total_return = (equity - initial) / initial if initial else 0
    if total_return >= PROFIT_TARGET_P1:
        cfg["halted"] = True
        save_config(cfg)
        return False, f"PROFIT TARGET {total_return*100:.1f}%"
    return True, f"OK — Daily: {daily_pct*100:+.2f}%, DD: {total_dd*100:.1f}%, Ret: {total_return*100:+.1f}%"

# ── Data Loading (all converted to UTC) ─────────────────────
def load_h1(symbol):
    """Load H1 data, convert MT5 server time to UTC."""
    for name in [symbol, symbol.replace('.', '_'), symbol + '_cash']:
        for suffix in ['_H1_MT5', '_H1', '']:
            p = H1_DATA_DIR / f"{name}{suffix}.csv"
            if p.exists():
                df = pd.read_csv(p, index_col=0, parse_dates=True)
                # MT5 data is in server time (UTC+2), convert to UTC
                if '_MT5' in suffix or '_cash' in name:
                    df.index = pd.to_datetime(df.index) - pd.Timedelta(hours=SERVER_OFFSET)
                    df.index = df.index.tz_localize('UTC')
                else:
                    df.index = pd.to_datetime(df.index, utc=True)
                if len(df) > 100:
                    return df[['Open', 'High', 'Low', 'Close']].dropna()
    return None

def fetch_fresh_yahoo(symbol, period='5d'):
    """Fetch fresh H1 data from Yahoo Finance (already in UTC)."""
    yahoo_map = {
        'XAUUSD': 'GC=F',
        'USDJPY': 'JPY=X',
        'EURUSD': 'EURUSD=X',
        'GBPUSD': 'GBPUSD=X',
    }
    tick = yahoo_map.get(symbol)
    if not tick:
        return None
    try:
        import yfinance as yf
        df = yf.download(tick, period=period, interval='1h', auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.index = pd.to_datetime(df.index, utc=True)
        return df[['Open', 'High', 'Low', 'Close']].dropna()
    except Exception as e:
        print(f"Yahoo fetch failed for {symbol}: {e}")
        return None

# ── MT5 State ───────────────────────────────────────────────
def read_mt5_state():
    if not STATE_FILE.exists():
        return None, None
    equity = 0.0
    symbols_info = {}
    with open(STATE_FILE, "r") as f:
        for row in csv.reader(f):
            if not row:
                continue
            if row[0] == "Equity":
                equity = float(row[1])
            else:
                symbols_info[row[0]] = {
                    "ask": float(row[1]), "bid": float(row[2]),
                    "contract": float(row[3]), "step": float(row[4]),
                    "pos_lot": float(row[5]),
                }
    return equity, symbols_info

def round_step(value, step):
    return round(value / step) * step

# ── Asian Session Momentum ──────────────────────────────────
def compute_asian_signal(df, config, equity, sym_info):
    """
    Compute Asian session momentum signal. All times in UTC.
    Returns (direction, lot_size) or (0, 0) if no signal.
    """
    if df is None or len(df) < config['pre_hours'] + 20:
        return 0, 0.0
    
    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values
    hour = pd.Series(df.index.hour, index=df.index)
    
    # ATR
    tr = np.maximum(high - low, np.maximum(
        np.abs(high - np.roll(close, 1)),
        np.abs(low - np.roll(close, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    current_hour = hour.iloc[-1]
    session_open = config['session_open']
    
    # Only signal at session open hour (UTC)
    if current_hour != session_open:
        return 0, 0.0
    
    # Pre-session range (excludes current bar)
    pre_h = config['pre_hours']
    pre_high = np.max(high[-pre_h-1:-1])
    pre_low = np.min(low[-pre_h-1:-1])
    pre_range = pre_high - pre_low
    
    if pre_range < atr[-1] * 0.3:
        return 0, 0.0
    
    buffer = atr[-1] * config['atr_mult']
    current_close = close[-1]
    
    direction = 0
    if current_close > pre_high + buffer:
        direction = 1
    elif current_close < pre_low - buffer:
        direction = -1
    else:
        return 0, 0.0
    
    # Position sizing with contract size
    sl_distance = abs(current_close - (pre_low - buffer if direction == 1 else pre_high + buffer))
    if sl_distance <= 0:
        return 0, 0.0
    
    symbol = config['symbol']
    if symbol not in sym_info:
        return 0, 0.0
    
    contract_size = sym_info[symbol]['contract']
    risk_amount = equity * config['risk_pct'] / 100
    # ponytail: USDxxx pairs (USDJPY, USDCAD) have non-USD profit currency;
    # multiply by price to convert. XXXUSD pairs and indices need no conversion.
    if symbol.startswith("USD") and not symbol.endswith("USD") and '.cash' not in symbol:
        lot_size = risk_amount * current_close / (sl_distance * contract_size)
    else:
        lot_size = risk_amount / (sl_distance * contract_size)
    
    return direction, lot_size

# ── Donchian Breakout ───────────────────────────────────────
def compute_donchian_signal(df, config, equity, sym_info):
    """
    Compute Donchian channel breakout signal on H1 data.
    Returns target lot size or None (maintain current).
    """
    if df is None or len(df) < config['lookback'] + 5:
        return 0.0
    
    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values
    
    lookback = config['lookback']
    
    # Current and previous Donchian channels
    don_high = np.max(high[-lookback:])
    don_low = np.min(low[-lookback:])
    prev_don_high = np.max(high[-lookback-1:-1])
    prev_don_low = np.min(low[-lookback-1:-1])
    
    current_high = high[-1]
    current_low = low[-1]
    current_close = close[-1]
    
    symbol = config['symbol']
    if symbol not in sym_info:
        return 0.0
    
    info = sym_info[symbol]
    
    # Check for breakout
    direction = 0
    if current_high > prev_don_high:
        direction = 1
    elif current_low < prev_don_low:
        direction = -1
    
    if direction == 0:
        return None  # maintain current position
    
    # Position sizing with contract size
    sl_distance = don_high - don_low
    if sl_distance <= 0:
        return 0.0
    
    risk_amount = equity * config['risk_pct'] / 100
    lot_size = risk_amount / (sl_distance * info['contract'])
    step = info['step']
    clean_lots = round_step(lot_size, step)
    
    return clean_lots * direction

# ── Main ────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc)
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode not in ("open", "close", "check"):
        print(f"Usage: brain_cron.py [open|close|check] [dry]")
        return
    dry_run = len(sys.argv) > 2 and sys.argv[2] == "dry"

    equity, sym_info = read_mt5_state()
    if equity is None or equity <= 0:
        print("ERROR: Could not read MT5 state. Is the EA running?")
        return

    cfg = init_ftmo_tracking(equity)
    update_day_start(cfg, equity)
    ok, status = check_ftmo_rules(cfg, equity)
    print(f"FTMO: {status}")
    print(f"Time: {now.strftime('%Y-%m-%d %H:%M UTC')}  Mode: {mode.upper()}")

    if not ok:
        print("FTMO LIMIT BREACHED — flat all")
        if not dry_run:
            write_targets({"USDJPY": 0.0, "XAUUSD": 0.0})
        return

    targets = {}
    targets_sl = {}
    targets_tp = {}
    
    # Current prices for TP calculation
    current_prices = {
        sym: (info['ask'] + info['bid']) / 2
        for sym, info in (sym_info or {}).items()
    }

    # ── USDJPY Asian Session Momentum ──
    if mode == "close":
        targets["USDJPY"] = 0.0
        print("USDJPY: Closing Asian session trade")
    elif mode == "open":
        usdjpy_data = fetch_fresh_yahoo("USDJPY", period='2d')
        if usdjpy_data is None:
            usdjpy_data = load_h1("USDJPY")
        direction, lot_size = compute_asian_signal(usdjpy_data, ASIAN_CONFIG, equity, sym_info)
        if direction != 0 and lot_size > 0:
            info = sym_info.get("USDJPY")
            if info:
                clean_lots = round_step(lot_size, info['step'])
                if clean_lots >= info.get('step', 0.01):
                    targets["USDJPY"] = clean_lots * direction
                    print(f"USDJPY: Asian {'LONG' if direction > 0 else 'SHORT'} {clean_lots} lots")
                else:
                    print("USDJPY: Signal too small after rounding")
        else:
            print("USDJPY: No Asian session signal")
    else:
        # check mode — maintain current position
        current_pos = sym_info.get("USDJPY", {}).get("pos_lot", 0.0)
        targets["USDJPY"] = current_pos
        print(f"USDJPY: Maintaining current ({current_pos} lots)")
    
    # ── XAUUSD Donchian Breakout ──
    # Always fetch fresh data (Donchian needs current prices)
    xau_data = fetch_fresh_yahoo("XAUUSD", period='7d')  # 7d for 55-bar lookback
    if xau_data is None or len(xau_data) < 60:
        print("WARNING: Yahoo XAUUSD data insufficient, using cached")
        xau_data = load_h1("XAUUSD")
    
    if xau_data is not None:
        print(f"XAUUSD data: {len(xau_data)} bars, last={xau_data.index[-1]}")
    
    donchian_signal = compute_donchian_signal(xau_data, DONCHIAN_CONFIG, equity, sym_info)
    
    if donchian_signal is not None and donchian_signal != 0:
        targets["XAUUSD"] = donchian_signal
        # SL at Donchian channel boundary, TP at RR * channel width
        don_high = float(xau_data['High'].iloc[-55:].max())
        don_low = float(xau_data['Low'].iloc[-55:].min())
        channel_width = don_high - don_low
        rr = DONCHIAN_CONFIG['rr']
        if donchian_signal > 0:
            # LONG: SL below, TP above
            targets_sl["XAUUSD"] = don_low
            targets_tp["XAUUSD"] = don_high + channel_width * rr
        else:
            # SHORT: SL above, TP below
            targets_sl["XAUUSD"] = don_high
            targets_tp["XAUUSD"] = don_low - channel_width * rr
        print(f"XAUUSD: Donchian {'LONG' if donchian_signal > 0 else 'SHORT'} {abs(donchian_signal)} lots  SL={targets_sl['XAUUSD']:.2f}  TP={targets_tp['XAUUSD']:.2f}")
    elif donchian_signal is None:
        current_pos = sym_info.get("XAUUSD", {}).get("pos_lot", 0.0)
        targets["XAUUSD"] = current_pos
        if current_pos != 0 and xau_data is not None:
            don_high = float(xau_data['High'].iloc[-55:].max())
            don_low = float(xau_data['Low'].iloc[-55:].min())
            channel_width = don_high - don_low
            rr = DONCHIAN_CONFIG['rr']
            if current_pos > 0:
                targets_sl["XAUUSD"] = don_low
                targets_tp["XAUUSD"] = don_high + channel_width * rr
            else:
                targets_sl["XAUUSD"] = don_high
                targets_tp["XAUUSD"] = don_low - channel_width * rr
        print(f"XAUUSD: Maintaining current ({current_pos} lots)")
    else:
        targets["XAUUSD"] = 0.0
        print("XAUUSD: Flat")
    
    # Summary
    print(f"\n{'Symbol':<14} {'Target':>10}")
    print("-" * 26)
    for sym, lots in targets.items():
        print(f"{sym:<14} {lots:>10.2f}")
    
    if dry_run:
        print("\n[DRY RUN]")
        return
    
    # Include all tracked symbols
    all_tracked = {"USDJPY", "XAUUSD", "US100.cash", "US500.cash"}
    for sym in all_tracked:
        if sym not in targets:
            targets[sym] = 0.0
    
    write_targets(targets, targets_sl, targets_tp)

def write_targets(targets, sl_dict={}, tp_dict={}):
    """Write targets CSV with optional SL/TP prices. Format: symbol,lots,sl_price,tp_price"""
    
    tmp = TARGET_FILE.with_suffix('.tmp')
    with open(tmp, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["EXECUTE"])
        for sym, lots in targets.items():
            sl = float(sl_dict.get(sym, 0.0))
            tp = float(tp_dict.get(sym, 0.0))
            writer.writerow([sym, f"{lots:.2f}", f"{sl:.2f}" if sl > 0 else "0", f"{tp:.2f}" if tp > 0 else "0"])
    tmp.rename(TARGET_FILE)
    print(f"\nTargets sent ({len(targets)} symbols).")

if __name__ == "__main__":
    main()
