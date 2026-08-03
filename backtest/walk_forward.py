"""
Walk-forward validation.
Train on N years, test on M months, step forward M months, repeat.
Avoids overfitting that in-sample backtests hide.
"""
import pandas as pd
from dateutil.relativedelta import relativedelta
from backtesting import Backtest
from strategies.london_breakout import LondonBreakout


def walk_forward(
    df: pd.DataFrame,
    train_years: int = 2,
    test_months: int = 6,
    cash: float = 10_000,
    commission: float = 0.0002,
) -> list[dict]:
    results = []
    start = df.index[0].date()
    end = df.index[-1].date()

    window_start = start
    while True:
        train_end = window_start + relativedelta(years=train_years)
        test_end = train_end + relativedelta(months=test_months)

        if test_end > end:
            break

        train_df = df[str(window_start):str(train_end)]
        test_df = df[str(train_end):str(test_end)]

        if len(train_df) < 100 or len(test_df) < 20:
            window_start += relativedelta(months=test_months)
            continue

        # Optimize on train
        bt_train = Backtest(train_df, LondonBreakout, cash=cash,
                            commission=commission, exclusive_orders=True)
        opt = bt_train.optimize(
            rr=[1.0, 1.5, 2.0],
            buffer_pips=[3, 5, 8],
            maximize="Sharpe Ratio",
            return_heatmap=False,
        )
        best_rr = opt._strategy.rr
        best_buf = opt._strategy.buffer_pips

        # Test on unseen data with best params
        bt_test = Backtest(test_df, LondonBreakout, cash=cash,
                           commission=commission, exclusive_orders=True)

        class Tuned(LondonBreakout):
            rr = best_rr
            buffer_pips = best_buf

        bt_test2 = Backtest(test_df, Tuned, cash=cash,
                            commission=commission, exclusive_orders=True)
        stats = bt_test2.run()

        results.append({
            "train_start": str(window_start),
            "train_end": str(train_end),
            "test_start": str(train_end),
            "test_end": str(test_end),
            "sharpe": round(stats["Sharpe Ratio"], 3),
            "return_pct": round(stats["Return [%]"], 2),
            "max_dd_pct": round(stats["Max. Drawdown [%]"], 2),
            "win_rate": round(stats["Win Rate [%]"], 2),
            "trades": stats["# Trades"],
            "best_rr": best_rr,
            "best_buf": best_buf,
        })

        window_start += relativedelta(months=test_months)

    return results


def summarize(results: list[dict]) -> dict:
    import statistics
    sharpes = [r["sharpe"] for r in results if r["trades"] > 0]
    returns = [r["return_pct"] for r in results if r["trades"] > 0]
    return {
        "windows": len(results),
        "positive_windows": sum(1 for r in returns if r > 0),
        "avg_sharpe": round(statistics.mean(sharpes), 3) if sharpes else 0,
        "avg_return_pct": round(statistics.mean(returns), 2) if returns else 0,
        "worst_dd": min(r["max_dd_pct"] for r in results) if results else 0,
    }
