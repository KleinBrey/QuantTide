from __future__ import annotations

import unittest

import pandas as pd

from backend.app.strategy.registry import (
    execute_strategy,
    find_strategy,
    strategy_list,
)
from backend.app.strategy.result import format_strategy_result
from backend.app.strategy.implementations.recent_volume_breakout import (
    RESULT_COLUMNS,
    VolumeBreakoutStrategy,
)


class FakeStockDailyBasicRepository:
    def get_table_data(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": ["PASS.SZ", "QUIET.SZ", "SMALL.SZ"],
                "market_cap": [20_000_000_000, 20_000_000_000, 5_000_000_000],
            }
        )


def make_bars(symbol: str, recent_volume: float, final_close: float) -> pd.DataFrame:
    close = [100.0] * 20 + [101.0, 102.0, 103.0, 104.0, final_close]
    volume = [100.0] * 20 + [recent_volume] * 5
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": pd.date_range("2026-07-01", periods=25, freq="D"),
            "close": close,
            "volume": volume,
        }
    )


class VolumeBreakoutStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = VolumeBreakoutStrategy()
        self.stock_daily_basic = FakeStockDailyBasicRepository().get_table_data()
        self.stocks = pd.DataFrame(
            {
                "symbol": ["PASS.SZ", "QUIET.SZ", "SMALL.SZ"],
                "name": ["放量股份", "缩量股份", "小盘股份"],
                "exchange": ["SZ", "SZ", "SZ"],
                "market": ["主板", "主板", "主板"],
            }
        )
        self.bars = pd.concat(
            [
                make_bars("PASS.SZ", 180, 106),
                make_bars("QUIET.SZ", 120, 106),
                make_bars("SMALL.SZ", 180, 106),
            ],
            ignore_index=True,
        )
        self.hot_stocks = pd.DataFrame(
            {
                "symbol": ["QUIET.SZ", "PASS.SZ", "SMALL.SZ"],
                "hot_value": [3000.0, 2000.0, 1000.0],
            }
        )

    def test_selects_matching_stock_and_exposes_api_fields(self) -> None:
        result = self.strategy.select(
            self.stocks,
            self.bars,
            self.hot_stocks,
            self.stock_daily_basic,
        )

        self.assertEqual(result.columns.tolist(), RESULT_COLUMNS)
        self.assertEqual(result["symbol"].tolist(), ["PASS.SZ"])
        self.assertAlmostEqual(result.loc[0, "volume_ratio"], 1.8)
        self.assertAlmostEqual(result.loc[0, "latest_5d_pct"], 0.06)
        self.assertEqual(result.loc[0, "hot_rank"], 2)

    def test_payload_is_json_ready_and_reports_total_before_limit(self) -> None:
        selected = self.strategy.select(
            self.stocks,
            self.bars,
            self.hot_stocks,
            self.stock_daily_basic,
        )
        payload = format_strategy_result("recent_volume_breakout", selected, limit=1)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["trade_date"], "2026-07-25")
        self.assertEqual(payload["items"][0]["latest_date"], "2026-07-25T00:00:00")
        self.assertEqual(payload["strategy"]["id"], "recent_volume_breakout")

    def test_empty_hot_ranking_returns_stable_columns(self) -> None:
        result = self.strategy.select(
            self.stocks,
            self.bars,
            pd.DataFrame(columns=["symbol", "hot_value"]),
            self.stock_daily_basic,
        )

        self.assertTrue(result.empty)
        self.assertEqual(result.columns.tolist(), RESULT_COLUMNS)

    def test_registry_loads_metadata_and_executes_strategy_by_id(self) -> None:
        definitions = strategy_list()
        definition = find_strategy("recent_volume_breakout")

        self.assertIn("recent_volume_breakout", [item["id"] for item in definitions])
        self.assertEqual(definition["name"], "堆量1.5倍")

        result = execute_strategy(
            "recent_volume_breakout",
            stocks=self.stocks,
            daily_bars=self.bars,
            hot_stocks=self.hot_stocks,
            stock_daily_basic=self.stock_daily_basic,
        )
        self.assertEqual(result["symbol"].tolist(), ["PASS.SZ"])

    def test_registry_rejects_unknown_strategy_id(self) -> None:
        with self.assertRaises(KeyError):
            find_strategy("unknown-strategy")


if __name__ == "__main__":
    unittest.main()
