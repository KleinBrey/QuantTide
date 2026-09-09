from __future__ import annotations

import unittest

import pandas as pd

from backend.app.strategy.implementations.today_volume_breakout import (
    RESULT_COLUMNS,
    TodayVolumeBreakoutStrategy,
)
from backend.app.strategy.registry import execute_strategy, find_strategy


class FakeStockDailyBasicRepository:
    def get_table_data(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": ["PASS.SZ", "FLAT.SZ", "SMALL.SZ", "LIMIT.SZ"],
                "market_cap": [
                    20_000_000_000,
                    20_000_000_000,
                    5_000_000_000,
                    10_000_000_000,
                ],
            }
        )


def make_bars(symbol: str, latest_volume: float, latest_close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": pd.date_range("2026-07-01", periods=11, freq="D"),
            "close": [100.0] * 10 + [latest_close],
            "volume": [100.0] * 10 + [latest_volume],
        }
    )


class TodayVolumeBreakoutStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = TodayVolumeBreakoutStrategy()
        self.stock_daily_basic = FakeStockDailyBasicRepository().get_table_data()
        self.stocks = pd.DataFrame(
            {
                "symbol": ["PASS.SZ", "FLAT.SZ", "SMALL.SZ", "LIMIT.SZ"],
                "name": ["放量股份", "平盘股份", "小盘股份", "百亿股份"],
                "exchange": ["SZ", "SZ", "SZ", "SZ"],
                "market": ["主板", "主板", "主板", "主板"],
            }
        )
        self.bars = pd.concat(
            [
                make_bars("PASS.SZ", 200, 101),
                make_bars("FLAT.SZ", 300, 100),
                make_bars("SMALL.SZ", 300, 101),
                make_bars("LIMIT.SZ", 300, 101),
            ],
            ignore_index=True,
        )
        self.hot_stocks = pd.DataFrame(
            {
                "symbol": ["FLAT.SZ", "PASS.SZ", "SMALL.SZ", "LIMIT.SZ"],
                "hot_value": [4000.0, 3000.0, 2000.0, 1000.0],
            }
        )

    def test_selects_latest_positive_two_times_volume_stock(self) -> None:
        result = self.strategy.select(
            self.stocks,
            self.bars,
            self.hot_stocks,
            self.stock_daily_basic,
        )

        self.assertEqual(result.columns.tolist(), RESULT_COLUMNS)
        self.assertEqual(result["symbol"].tolist(), ["PASS.SZ"])
        self.assertAlmostEqual(result.loc[0, "volume_ratio"], 2.0)
        self.assertAlmostEqual(result.loc[0, "latest_1d_pct"], 0.01)
        self.assertEqual(result.loc[0, "hot_rank"], 2)

    def test_registry_loads_and_executes_strategy(self) -> None:
        definition = find_strategy("today_volume_breakout")
        self.assertEqual(definition["name"], "巨量人气股(大市值)")

        result = execute_strategy(
            "today_volume_breakout",
            stocks=self.stocks,
            daily_bars=self.bars,
            hot_stocks=self.hot_stocks,
            stock_daily_basic=self.stock_daily_basic,
        )
        self.assertEqual(result["symbol"].tolist(), ["PASS.SZ"])


if __name__ == "__main__":
    unittest.main()
