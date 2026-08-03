import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import time

# --- CONFIGURATION ---
SYMBOLS = ["XAUUSD", "US100.cash", "US500.cash", "USDJPY"]
TARGET_VOL = 0.15          # 15% annualized volatility target
MAX_LEVERAGE_PER_SYM = 5.0 # Safety cap
ACCOUNT_CURRENCY = "USD"
# ---------------------

def get_data(symbol, num_bars=300):
    """Fetch daily bars from MT5."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, num_bars)
    if rates is None or len(rates) == 0:
        print(f"Failed to get data for {symbol}")
        return None
        
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    return df

def calculate_target_position(df, account_equity):
    """Calculate the target dollar exposure based on TSMOM and Carver vol targeting."""
    close = df['close']
    
    if len(close) < 260:
        return 0.0 # Not enough data
        
    returns = close.pct_change()
    
    # 1. Volatility (36-day EWMA)
    vol = returns.ewm(span=36).std() * np.sqrt(252)
    current_vol = vol.iloc[-1]
    
    # 2. Momentum (63, 126, 252 days)
    ret3 = (close.iloc[-1] / close.iloc[-64]) - 1
    ret6 = (close.iloc[-1] / close.iloc[-127]) - 1
    ret12 = (close.iloc[-1] / close.iloc[-253]) - 1
    
    signal = (np.sign(ret3) + np.sign(ret6) + np.sign(ret12)) / 3.0
    
    if current_vol == 0 or np.isnan(current_vol):
        return 0.0
        
    # 3. Target Weight
    # Formula: (Target Vol / Current Vol) * Signal / Num_Assets
    weight = (TARGET_VOL / current_vol) * signal / len(SYMBOLS)
    
    # Cap leverage
    weight = np.clip(weight, -MAX_LEVERAGE_PER_SYM, MAX_LEVERAGE_PER_SYM)
    
    target_exposure_usd = account_equity * weight
    return target_exposure_usd

def get_symbol_info(symbol):
    info = mt5.symbol_info(symbol)
    if info is None:
        return None
    return {
        'contract_size': info.trade_contract_size,
        'point': info.point,
        'digits': info.digits,
        'min_lot': info.volume_min,
        'max_lot': info.volume_max,
        'step_lot': info.volume_step,
        'ask': info.ask,
        'bid': info.bid,
        'currency_profit': info.currency_profit,
        'currency_base': info.currency_base
    }

def convert_to_lots(target_usd, symbol, info):
    """Convert target USD exposure to MT5 lots."""
    if target_usd == 0:
        return 0.0
        
    price = info['ask'] if target_usd > 0 else info['bid']
    
    # Base calculation
    if info['currency_profit'] == 'USD' and info['currency_base'] != 'USD':
        # E.g., XAUUSD, EURUSD. Contract is in Base. 
        # 1 lot = contract_size * Base. Exposure = 1 lot * price * contract_size
        lot_value_usd = price * info['contract_size']
        
    elif info['currency_base'] == 'USD':
        # E.g., USDJPY, USDCAD. 
        # 1 lot = contract_size * USD. 
        lot_value_usd = info['contract_size']
        
    elif symbol in ["US30.cash", "US100.cash", "US500.cash"]:
        # Indices are usually quoted in USD
        lot_value_usd = price * info['contract_size']
        
    else:
        # Cross pairs or other currencies need exchange rate conversion (simplified out for this 4-asset focused list)
        print(f"Warning: USD conversion complex for {symbol}, assuming USD quoted.")
        lot_value_usd = price * info['contract_size']
        
    raw_lots = abs(target_usd) / lot_value_usd
    
    # Round to nearest valid step
    step = info['step_lot']
    lots = round(raw_lots / step) * step
    
    # Constrain
    lots = max(info['min_lot'], min(lots, info['max_lot']))
    
    return lots if target_usd > 0 else -lots

def close_position(ticket, symbol, current_type, lot):
    """Close an open position."""
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if current_type == mt5.ORDER_TYPE_SELL else tick.bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if current_type == mt5.ORDER_TYPE_SELL else mt5.ORDER_TYPE_SELL,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": 123456,
        "comment": "TSMOM Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Close failed for {symbol}: {result.comment}")
    else:
        print(f"Closed {symbol} pos {ticket}")

def open_position(symbol, lots):
    """Open a new position."""
    if lots == 0: return
    
    is_buy = lots > 0
    vol = abs(lots)
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if is_buy else tick.bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": vol,
        "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
        "price": price,
        "deviation": 20,
        "magic": 123456,
        "comment": "TSMOM Open",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Open failed for {symbol}: {result.comment}")
    else:
        print(f"Opened {'BUY' if is_buy else 'SELL'} {vol} {symbol} at {price}")

def main():
    if not mt5.initialize():
        print("MT5 initialize failed")
        return
        
    account = mt5.account_info()
    if account is None:
        print("Failed to get account info")
        return
        
    equity = account.equity
    print(f"Account Equity: ${equity:.2f}")
    
    # 1. Calculate Target Positions
    targets = {}
    for sym in SYMBOLS:
        mt5.symbol_select(sym, True)
        df = get_data(sym)
        if df is not None:
            target_usd = calculate_target_position(df, equity)
            info = get_symbol_info(sym)
            if info:
                target_lots = convert_to_lots(target_usd, sym, info)
                targets[sym] = target_lots
                print(f"{sym}: Target USD: ${target_usd:.2f} -> Lots: {target_lots}")
                
    # 2. Rebalance
    print("\n--- Rebalancing ---")
    positions = mt5.positions_get()
    open_syms = {}
    
    if positions:
        for pos in positions:
            if pos.symbol in SYMBOLS and pos.magic == 123456:
                open_syms[pos.symbol] = pos
                
    for sym in SYMBOLS:
        target_lot = targets.get(sym, 0.0)
        current_pos = open_syms.get(sym)
        
        if current_pos:
            is_long = current_pos.type == mt5.ORDER_TYPE_BUY
            current_lot_signed = current_pos.volume if is_long else -current_pos.volume
            
            # Simple rebalance: if sign changed, or if we want flat, close it.
            # (We don't micro-adjust sizes daily to save on spreads. We only trade on signal flips or massive vol regime changes)
            if np.sign(target_lot) != np.sign(current_lot_signed) or target_lot == 0:
                close_position(current_pos.ticket, sym, current_pos.type, current_pos.volume)
                # Open new direction if needed
                if target_lot != 0:
                    time.sleep(1)
                    open_position(sym, target_lot)
            else:
                print(f"{sym}: Holding existing position (Dir: {'LONG' if is_long else 'SHORT'})")
        else:
            if target_lot != 0:
                open_position(sym, target_lot)

    mt5.shutdown()

if __name__ == "__main__":
    main()
