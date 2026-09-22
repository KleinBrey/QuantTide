import unittest

import pandas as pd

from backend.quant.backtest.engine import (
    BacktestConfig,
    ConfirmedVolumeBreakoutBacktest,
)


class ScheduledSignalsStrategy:
    def __init__(self, signals_by_date: dict[pd.Timestamp, list[dict[str, object]]]):
        self.signals_by_date = signals_by_date

    def select(
        self,
        trade_date,
        stocks,
        daily_bars,
        hot_stocks,
        stock_daily_basic,
    ) -> pd.DataFrame:
        del stocks, daily_bars, hot_stocks, stock_daily_basic
        return pd.DataFrame(
            self.signals_by_date.get(pd.Timestamp(trade_date).normalize(), [])
        )


def signal(symbol: str, confirm_date: str, rank: int) -> dict[str, object]:
    return {
        "symbol": symbol,
        "name": symbol,
        "breakout_date": pd.Timestamp(confirm_date) - pd.Timedelta(days=1),
        "confirm_date": pd.Timestamp(confirm_date),
        "stop_loss_price": 5.0,
        "take_profit_price": 20.0,
        "selection_rank": rank,
    }


class ConfirmedVolumeBreakoutBacktestTest(unittest.TestCase):
    def test_refills_open_slots_and_reports_capacity_skips(self) -> None:
        dates = pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"])
        bars = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.0,
                    "volume": 1_000.0,
                }
                for trade_date in dates
                for symbol in ["A", "B", "C", "D"]
            ]
        )
        strategy = ScheduledSignalsStrategy(
            {
                dates[0]: [signal("A", "2026-01-02", 1)],
                dates[1]: [
                    signal("B", "2026-01-03", 1),
                    signal("C", "2026-01-03", 2),
                ],
                dates[2]: [signal("D", "2026-01-04", 1)],
            }
        )
        backtest = ConfirmedVolumeBreakoutBacktest(
            BacktestConfig(
                initial_cash=1_000.0,
                start_date="2026-01-02",
                end_date="2026-01-04",
                max_positions=2,
                lot_size=1,
            ),
            strategy=strategy,
        )

        result = backtest.run(
            stocks=pd.DataFrame(),
            daily_bars=bars,
            hot_stocks=pd.DataFrame(),
            stock_daily_basic=pd.DataFrame(),
        )
        summary = result.summary()
        buys = result.trades[result.trades["side"] == "BUY"]

        self.assertEqual(list(buys["symbol"]), ["A", "B"])
        self.assertEqual(list(buys["quantity"]), [50, 50])
        self.assertEqual(list(buys["position_pct"]), [0.5, 0.5])
        self.assertEqual(summary["qualified_signal_count"], 4)
        self.assertEqual(summary["executed_signal_count"], 2)
        self.assertEqual(summary["skipped_full_position_count"], 2)
        self.assertEqual(summary["open_positions"], 2)


if __name__ == "__main__":
    unittest.main()
