from __future__ import annotations

import unittest

import pandas as pd

from backend.app.strategy.implementations.second_rebound_short import (
    RESULT_COLUMNS,
    StrategyConfig,
    latest_filter_counts,
    run_second_rebound_short_strategy,
)
from backend.app.strategy.registry import execute_strategy, find_strategy


class FakeStockDailyBasicRepository:
    def get_table_data(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"symbol": ["TEST.SZ"], "market_cap": [20_000_000_000]}
        )


def make_short_bars(*, long_upper_wick: bool = False) -> pd.DataFrame:
    close = [100.0] * 50 + [118.0] + [112.0, 108.0, 104.0, 101.0]
    close += [103.0, 106.0, 109.0, 112.0, 114.0, 115.0, 116.0, 116.0, 116.0]
    close += [110.0 if long_upper_wick else 108.0, 103.0]

    size = len(close)
    frame = pd.DataFrame(
        {
            "symbol": "TEST.SZ",
            "date": pd.bdate_range("2026-01-01", periods=size),
            "open": close,
            "high": [101.0] * size,
            "low": [99.0] * size,
            "close": close,
            "volume": [100.0] * size,
            "amount": [300_000.0] * size,
        }
    )

    frame.loc[50, ["open", "high", "low", "close"]] = [116.0, 120.0, 115.0, 118.0]
    frame.loc[54, "low"] = 100.0

    rejection_index = size - 2
    if long_upper_wick:
        frame.loc[rejection_index, ["open", "high", "low", "close"]] = [112.0, 120.0, 109.0, 110.0]
    else:
        frame.loc[rejection_index, ["open", "high", "low", "close"]] = [117.0, 119.0, 107.0, 108.0]
    frame.loc[rejection_index, "volume"] = 200.0
    frame.loc[size - 1, ["open", "high", "low", "close"]] = [107.0, 108.0, 102.0, 103.0]
    return frame


class SecondReboundShortStrategyTests(unittest.TestCase):
    def test_thresholds_can_be_overridden_with_config(self) -> None:
        result = run_second_rebound_short_strategy(
            make_short_bars(),
            StrategyConfig(min_volume_ratio=3.0),
        )

        self.assertFalse(result.iloc[-2]["rejection_signal"])
        self.assertFalse(result.iloc[-1]["follow_signal"])

    def test_detects_big_bear_and_follow_through(self) -> None:
        result = run_second_rebound_short_strategy(make_short_bars())

        self.assertTrue(result.iloc[-2]["big_bear"])
        self.assertTrue(result.iloc[-2]["rejection_signal"])
        self.assertTrue(result.iloc[-1]["follow_signal"])
        self.assertEqual(dict(latest_filter_counts(result))["次日继续下跌确认"], 1)

    def test_accepts_long_upper_wick_as_rejection(self) -> None:
        result = run_second_rebound_short_strategy(
            make_short_bars(long_upper_wick=True)
        )

        self.assertTrue(result.iloc[-2]["long_upper_wick"])
        self.assertTrue(result.iloc[-2]["rejection_signal"])
        self.assertTrue(result.iloc[-1]["follow_signal"])

    def test_waits_for_follow_through_before_returning_signal(self) -> None:
        bars = make_short_bars().iloc[:-1]
        result = run_second_rebound_short_strategy(bars)

        self.assertTrue(result.iloc[-1]["rejection_signal"])
        self.assertFalse(result.iloc[-1]["signal"])

    def test_strategy_is_registered_and_returns_frontend_fields(self) -> None:
        bars = make_short_bars().rename(columns={"date": "trade_date"})
        stocks = pd.DataFrame(
            {
                "symbol": ["TEST.SZ"],
                "name": ["测试股份"],
                "exchange": ["SZ"],
                "market": ["主板"],
            }
        )
        hot_stocks = pd.DataFrame(
            {"symbol": ["TEST.SZ"], "hot_value": [1000.0]}
        )

        result = execute_strategy(
            "second-rebound-short",
            stocks=stocks,
            daily_bars=bars,
            hot_stocks=hot_stocks,
            stock_daily_basic=FakeStockDailyBasicRepository().get_table_data(),
        )

        definition = find_strategy("second-rebound-short")
        self.assertEqual(definition["name"], "二次冲高做空")
        self.assertEqual(result.columns.tolist(), RESULT_COLUMNS)
        self.assertEqual(result["symbol"].tolist(), ["TEST.SZ"])
        self.assertEqual(result.loc[0, "signal_stage"], "跟随确认")


if __name__ == "__main__":
    unittest.main()
