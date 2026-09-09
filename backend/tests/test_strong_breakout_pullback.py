from __future__ import annotations

import unittest

import pandas as pd

from backend.app.strategy.implementations.breakout_pullback_n import (
    RESULT_COLUMNS,
    StrategyConfig,
    run_strong_breakout_pullback_strategy,
)
from backend.app.strategy.registry import execute_strategy, find_strategy


class FakeStockDailyBasicRepository:
    def get_table_data(self) -> pd.DataFrame:
        return pd.DataFrame({"symbol": ["TEST.SZ"], "market_cap": [20_000_000_000]})


def make_bars(
    *,
    pullback_volume: float = 100.0,
    confirm_volume: float = 160.0,
) -> pd.DataFrame:
    close = [100.0] * 20
    close += [103.0, 106.0, 110.0, 114.0, 116.0]
    close += [114.0, 112.0, 110.0, 111.0, 110.0]
    close += [114.0]

    size = len(close)
    frame = pd.DataFrame(
        {
            "symbol": "TEST.SZ",
            "date": pd.bdate_range("2026-01-01", periods=size),
            "open": close,
            "high": [101.0] * size,
            "low": [99.0] * size,
            "close": close,
            "volume": [100.0] * 20
            + [200.0] * 5
            + [pullback_volume] * 5
            + [confirm_volume],
        }
    )

    for index in range(20, 25):
        previous_close = frame.loc[index - 1, "close"]
        frame.loc[index, ["open", "high", "low"]] = [
            previous_close,
            frame.loc[index, "close"] + 1,
            previous_close - 1,
        ]

    for index in range(25, 30):
        frame.loc[index, ["open", "high", "low"]] = [
            frame.loc[index - 1, "close"],
            frame.loc[index, "close"] + 1,
            frame.loc[index, "close"] - 1,
        ]

    frame.loc[30, ["open", "high", "low"]] = [110.0, 115.0, 109.0]
    return frame


class StrongBreakoutPullbackStrategyTests(unittest.TestCase):
    def test_thresholds_can_be_overridden_with_config(self) -> None:
        result = run_strong_breakout_pullback_strategy(
            make_bars(),
            StrategyConfig(min_confirm_volume_ratio=2.0),
        )

        self.assertTrue(result.empty)

    def test_detects_three_stage_pattern(self) -> None:
        result = run_strong_breakout_pullback_strategy(make_bars())

        self.assertEqual(result["symbol"].tolist(), ["TEST.SZ"])
        self.assertGreaterEqual(result.loc[0, "breakout_return"], 0.10)
        self.assertAlmostEqual(result.loc[0, "pullback_volume_ratio"], 0.5)
        self.assertAlmostEqual(result.loc[0, "volume_ratio"], 1.6)

    def test_requires_pullback_volume_to_contract(self) -> None:
        result = run_strong_breakout_pullback_strategy(
            make_bars(pullback_volume=180.0, confirm_volume=260.0)
        )

        self.assertTrue(result.empty)

    def test_requires_confirmation_volume_to_expand(self) -> None:
        result = run_strong_breakout_pullback_strategy(make_bars(confirm_volume=120.0))

        self.assertTrue(result.empty)

    def test_ignores_signal_from_an_older_stock_date(self) -> None:
        current = make_bars()
        older = make_bars()
        older["symbol"] = "OLD.SZ"
        older["date"] = older["date"] - pd.Timedelta(days=3)

        result = run_strong_breakout_pullback_strategy(
            pd.concat([older, current], ignore_index=True)
        )

        self.assertEqual(result["symbol"].tolist(), ["TEST.SZ"])

    def test_strategy_is_registered_and_returns_frontend_fields(self) -> None:
        bars = make_bars().rename(columns={"date": "trade_date"})
        stocks = pd.DataFrame(
            {
                "symbol": ["TEST.SZ"],
                "name": ["测试股份"],
                "exchange": ["SZ"],
            }
        )
        hot_stocks = pd.DataFrame({"symbol": ["TEST.SZ"], "hot_value": [1000.0]})

        result = execute_strategy(
            "strong-breakout-pullback",
            stocks=stocks,
            daily_bars=bars,
            hot_stocks=hot_stocks,
            stock_daily_basic=FakeStockDailyBasicRepository().get_table_data(),
        )

        definition = find_strategy("strong-breakout-pullback")
        self.assertEqual(definition["name"], "突破回调 N 字企稳")
        self.assertEqual(result.columns.tolist(), RESULT_COLUMNS)
        self.assertEqual(result["symbol"].tolist(), ["TEST.SZ"])
        self.assertEqual(result.loc[0, "signal_stage"], "放量企稳")


if __name__ == "__main__":
    unittest.main()
