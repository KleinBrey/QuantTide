from __future__ import annotations

import unittest

import pandas as pd

from backend.app.strategy.implementations.today_emotion_reversal import (
    RESULT_COLUMNS,
    TodayEmotionReversalStrategy,
)
from backend.app.strategy.registry import execute_strategy, find_strategy


class FakeStockDailyBasicRepository:
    def get_table_data(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": [
                    "PASS.SZ",
                    "BOUNDARY.SZ",
                    "GAP_LIMIT.SZ",
                    "PREVIOUS_LOW.SZ",
                    "SMALL.SZ",
                    "STALE.SZ",
                ],
                "market_cap": [
                    20_000_000_000,
                    20_000_000_000,
                    20_000_000_000,
                    20_000_000_000,
                    5_000_000_000,
                    20_000_000_000,
                ],
            }
        )


def make_bars(
    symbol: str,
    *,
    first_close: float = 100.0,
    previous_close: float = 100.0,
    latest_open: float = 104.0,
    latest_close: float = 103.0,
    start: str = "2026-07-01",
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": pd.date_range(start, periods=3, freq="D"),
            "open": [first_close, previous_close, latest_open],
            "close": [first_close, previous_close, latest_close],
        }
    )


class TodayEmotionReversalStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = TodayEmotionReversalStrategy()
        self.stock_daily_basic = FakeStockDailyBasicRepository().get_table_data()
        symbols = [
            "PASS.SZ",
            "BOUNDARY.SZ",
            "GAP_LIMIT.SZ",
            "PREVIOUS_LOW.SZ",
            "SMALL.SZ",
            "STALE.SZ",
        ]
        self.stocks = pd.DataFrame(
            {
                "symbol": symbols,
                "name": [
                    "反转股份",
                    "边界股份",
                    "高开边界",
                    "跌幅超限",
                    "小盘股份",
                    "过期信号",
                ],
                "exchange": ["SZ"] * len(symbols),
                "market": ["主板"] * len(symbols),
            }
        )
        self.bars = pd.concat(
            [
                make_bars(
                    "PASS.SZ",
                    previous_close=98.0,
                    latest_open=102.0,
                    latest_close=101.0,
                ),
                make_bars(
                    "BOUNDARY.SZ",
                    previous_close=95.0,
                    latest_open=98.0,
                    latest_close=97.85,
                ),
                make_bars("GAP_LIMIT.SZ", latest_open=103.0),
                make_bars(
                    "PREVIOUS_LOW.SZ",
                    previous_close=94.0,
                    latest_open=98.0,
                    latest_close=97.0,
                ),
                make_bars("SMALL.SZ"),
                make_bars("STALE.SZ", start="2026-06-27"),
            ],
            ignore_index=True,
        )
        self.hot_stocks = pd.DataFrame(
            {
                "symbol": [
                    "BOUNDARY.SZ",
                    "GAP_LIMIT.SZ",
                    "PASS.SZ",
                    "PREVIOUS_LOW.SZ",
                    "SMALL.SZ",
                    "STALE.SZ",
                ],
                "hot_value": [6000.0, 5000.0, 4000.0, 3000.0, 2000.0, 1000.0],
            }
        )

    def test_selects_matching_stocks_and_sorts_by_hot_rank(self) -> None:
        result = self.strategy.select(
            self.stocks,
            self.bars,
            self.hot_stocks,
            self.stock_daily_basic,
        )

        self.assertEqual(result.columns.tolist(), RESULT_COLUMNS)
        self.assertEqual(result["symbol"].tolist(), ["BOUNDARY.SZ", "PASS.SZ"])
        self.assertAlmostEqual(result.loc[0, "previous_1d_pct"], -0.05)
        self.assertAlmostEqual(result.loc[0, "latest_1d_pct"], 0.03)
        self.assertEqual(result["hot_rank"].tolist(), [1, 3])

    def test_open_gap_threshold_is_strict(self) -> None:
        result = self.strategy.select(
            self.stocks,
            self.bars,
            self.hot_stocks,
            self.stock_daily_basic,
        )

        self.assertNotIn("GAP_LIMIT.SZ", result["symbol"].tolist())

    def test_registry_loads_and_executes_strategy(self) -> None:
        definition = find_strategy("today_emotion_reversal")
        self.assertEqual(definition["name"], "情绪反转人气股(大市值)")

        result = execute_strategy(
            "today_emotion_reversal",
            stocks=self.stocks,
            daily_bars=self.bars,
            hot_stocks=self.hot_stocks,
            stock_daily_basic=self.stock_daily_basic,
        )
        self.assertEqual(result["symbol"].tolist(), ["BOUNDARY.SZ", "PASS.SZ"])


if __name__ == "__main__":
    unittest.main()
