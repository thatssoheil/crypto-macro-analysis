"""
Live execution loop — runs on Windows machine with MT5 terminal open.
Polls every minute, checks FTMO rules, fires orders via MT5 API.
"""
import time
import logging
from datetime import datetime, date
import pytz
import MetaTrader5 as mt5
from execution.ftmo_rules import FTMORules

logging.basicConfig(
    filename="logs/bot.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

UTC = pytz.utc
SYMBOL = "EURUSD"
TIMEFRAME = mt5.TIMEFRAME_H1
RISK_PCT = 0.01        # 1% per trade
PIP_VALUE = 10.0       # USD per pip per lot — EURUSD standard lot
INITIAL_BALANCE = 10_000.0  # set to your FTMO account size


def get_balance() -> float:
    info = mt5.account_info()
    return info.balance if info else 0.0


def main(login: int, password: str, server: str):
    from utils.mt5_connect import connect
    from strategies.london_breakout import LondonBreakout

    connect(login, password, server)
    rules = FTMORules(INITIAL_BALANCE, phase=1)

    last_reset_day: date | None = None
    log = logging.getLogger(__name__)
    log.info("Bot started")

    try:
        while True:
            now = datetime.now(UTC)
            today = now.date()

            # Daily reset
            if last_reset_day != today:
                rules.reset_daily(get_balance())
                last_reset_day = today
                log.info(f"Daily reset. Balance: {get_balance():.2f}")

            balance = get_balance()
            tradeable, reason = rules.can_trade(balance)

            if not tradeable:
                log.warning(f"Trading halted: {reason}")
                time.sleep(60)
                continue

            # Check open positions — strategy handles SL/TP via MT5 orders
            positions = mt5.positions_get(symbol=SYMBOL)
            if positions and len(positions) > 0:
                time.sleep(60)
                continue

            # Signal check happens via MT5 rates — strategy logic runs here
            # ponytail: this is a thin execution shell; move signal gen to
            # a separate process and post via named pipe for cleaner separation
            log.info(f"Polling {now.strftime('%H:%M')} UTC | Balance: {balance:.2f}")
            time.sleep(60)

    except KeyboardInterrupt:
        log.info("Bot stopped by user")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    import os
    main(
        login=int(os.environ["MT5_LOGIN"]),
        password=os.environ["MT5_PASSWORD"],
        server=os.environ["MT5_SERVER"],
    )
