from __future__ import annotations

import unittest

import pandas as pd

from backend.app.strategy.implementations.panic_reversal_v import (
    RESULT_COLUMNS,
    PanicReversalVStrategy,
)
from backend.app.strategy.registry import execute_strategy
from backend.app.strategy.result import format_strategy_result


def make_bars(
    symbol: str,
    *,
    recent_volume: float = 150.0,
    descending: bool = True,
) -> pd.DataFrame:
    closes = list(range(123, 100, -1)) if descending else list(range(101, 124))
    lows = [close - 1 for close in closes]
    volumes = [100.0] * 20 + [recent_volume] * 3
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": pd.date_range("2026-07-01", periods=23, freq="D"),
            "close": closes,
            "low": lows,
            "volume": volumes,
        }
    )


class PanicReversalVStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = PanicReversalVStrategy()
        self.stocks = pd.DataFrame(
            {
                "symbol": [
                    "PASS.SZ",
                    "QUIET.SZ",
                    "UP.SZ",
                    "SMALL.SZ",
                    "STOCK.SZ",
                    "STAR.SH",
                    "BEIJING.BJ",
                ],
                "name": [
                    "符合股份",
                    "未放量股份",
                    "上涨股份",
                    "百亿股份",
                    "ST测试",
                    "科创股份",
                    "北交股份",
                ],
                "exchange": ["SZ", "SZ", "SZ", "SZ", "SZ", "SH", "BJ"],
                "market": [
                    "主板",
                    "主板",
                    "主板",
                    "主板",
                    "主板",
                    "科创板",
                    "北交所",
                ],
            }
        )
        self.stock_daily_basic = pd.DataFrame(
            {
                "symbol": self.stocks["symbol"],
                "market_cap": [
                    20_000_000_000,
                    20_000_000_000,
                    20_000_000_000,
                    10_000_000_000,
                    20_000_000_000,
                    20_000_000_000,
                    20_000_000_000,
                ],
            }
        )
        self.daily_bars = pd.concat(
            [
                make_bars("PASS.SZ"),
                make_bars("QUIET.SZ", recent_volume=149.0),
                make_bars("UP.SZ", descending=False),
                make_bars("SMALL.SZ"),
                make_bars("STOCK.SZ"),
                make_bars("STAR.SH"),
                make_bars("BEIJING.BJ"),
            ],
            ignore_index=True,
        )
        self.hot_stocks = pd.DataFrame(
            {
                "symbol": ["UP.SZ", "PASS.SZ"],
                "hot_value": [2000.0, 1000.0],
            }
        )

    def test_selects_only_stock_matching_all_conditions(self) -> None:
        result = self.strategy.select(
            self.stocks,
            self.daily_bars,
            self.hot_stocks,
            self.stock_daily_basic,
        )

        self.assertEqual(result.columns.tolist(), RESULT_COLUMNS)
        self.assertEqual(result["symbol"].tolist(), ["PASS.SZ"])
        self.assertGreater(result.loc[0, "ma20"], result.loc[0, "ma10"])
        self.assertGreater(result.loc[0, "ma10"], result.loc[0, "ma5"])
        self.assertGreater(
            result.loc[0, "latest_close"], result.loc[0, "recent_3d_low"]
        )
        self.assertAlmostEqual(result.loc[0, "volume_ratio"], 1.5)
        self.assertEqual(result.loc[0, "hot_rank"], 2)

    def test_excludes_latest_close_at_recent_three_bar_low(self) -> None:
        bars = make_bars("PASS.SZ")
        bars.loc[bars.index[-3:], "low"] = bars["close"].iloc[-1]

        result = self.strategy.select(
            self.stocks.iloc[[0]],
            bars,
            pd.DataFrame({"symbol": ["PASS.SZ"], "hot_value": [1000.0]}),
            self.stock_daily_basic.iloc[[0]],
        )

        self.assertTrue(result.empty)
        self.assertEqual(result.columns.tolist(), RESULT_COLUMNS)

    def test_market_cap_must_be_strictly_greater_than_10_billion(self) -> None:
        filtered = self.strategy.merge_stock_basic(
            self.stocks,
            self.stock_daily_basic,
        )
        filtered = self.strategy.filter_stocks(filtered)

        self.assertNotIn("SMALL.SZ", filtered["symbol"].tolist())
        self.assertNotIn("STOCK.SZ", filtered["symbol"].tolist())
        self.assertNotIn("STAR.SH", filtered["symbol"].tolist())
        self.assertNotIn("BEIJING.BJ", filtered["symbol"].tolist())

    def test_empty_hot_data_returns_empty_result(self) -> None:
        result = self.strategy.select(
            self.stocks,
            self.daily_bars,
            pd.DataFrame(columns=["symbol", "hot_value"]),
            self.stock_daily_basic,
        )

        self.assertTrue(result.empty)
        self.assertEqual(result.columns.tolist(), RESULT_COLUMNS)

    def test_filters_and_sorts_by_current_hot_rank(self) -> None:
        second_stock = pd.DataFrame(
            {
                "symbol": ["SECOND.SH"],
                "name": ["第二股份"],
                "exchange": ["SH"],
                "market": ["主板"],
            }
        )
        second_basic = pd.DataFrame(
            {"symbol": ["SECOND.SH"], "market_cap": [20_000_000_000]}
        )

        result = self.strategy.select(
            pd.concat([self.stocks, second_stock], ignore_index=True),
            pd.concat(
                [
                    self.daily_bars,
                    make_bars("SECOND.SH"),
                ],
                ignore_index=True,
            ),
            pd.DataFrame(
                {
                    "symbol": ["SECOND.SH", "PASS.SZ"],
                    "hot_value": [2000.0, 1000.0],
                }
            ),
            pd.concat([self.stock_daily_basic, second_basic], ignore_index=True),
        )

        self.assertEqual(result["symbol"].tolist(), ["SECOND.SH", "PASS.SZ"])
        self.assertEqual(result["hot_rank"].tolist(), [1, 2])

    def test_registry_and_result_payload_keep_working(self) -> None:
        result = execute_strategy(
            "panic-reversal",
            stocks=self.stocks,
            daily_bars=self.daily_bars,
            hot_stocks=self.hot_stocks,
            stock_daily_basic=self.stock_daily_basic,
        )
        payload = format_strategy_result("panic-reversal", result, limit=10)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["trade_date"], "2026-07-23")
        self.assertEqual(payload["strategy"]["id"], "panic-reversal")


if __name__ == "__main__":
    unittest.main()
