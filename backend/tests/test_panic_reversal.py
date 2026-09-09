from __future__ import annotations

import unittest

import pandas as pd

from backend.app.strategy.implementations.panic_reversal_v import (
    RESULT_COLUMNS,
    StrategyConfig,
    calculate_confirmed_signal,
    calculate_indicators,
    calculate_panic_signal,
    calculate_reversal_signal,
    run_panic_reversal_strategy,
)
from backend.app.strategy.registry import execute_strategy
from backend.app.strategy.result import format_strategy_result


class FakeStockDailyBasicRepository:
    def get_table_data(self) -> pd.DataFrame:
        return pd.DataFrame({"symbol": ["TEST.SZ"], "market_cap": [20_000_000_000]})


class PanicReversalStrategyTests(unittest.TestCase):
    def test_panic_thresholds_can_be_overridden_with_config(self) -> None:
        indicators = pd.DataFrame(
            {
                "down_count": [4.0],
                "drawdown_20": [-0.20],
                "return_5d": [-0.20],
                "atr_pct": [0.01],
                "volume_ratio": [2.0],
                "large_bear": [False],
            }
        )

        default_result = calculate_panic_signal(indicators.copy(), StrategyConfig())
        strict_result = calculate_panic_signal(
            indicators.copy(),
            StrategyConfig(panic_min_down_days=5),
        )

        self.assertTrue(default_result.loc[0, "panic_signal"])
        self.assertFalse(strict_result.loc[0, "panic_signal"])

    def test_vectorized_calculation_matches_per_symbol_reference(self) -> None:
        closes = [100.0] * 20 + [96.0, 92.0, 88.0, 80.0, 90.0, 95.0]
        first = pd.DataFrame(
            {
                "symbol": "FIRST.SZ",
                "date": pd.date_range("2026-07-01", periods=26),
                "open": [100.0] * 20 + [100.0, 96.0, 92.0, 88.0, 80.0, 90.0],
                "high": [101.0] * 20 + [101.0, 97.0, 93.0, 89.0, 91.0, 96.0],
                "low": [99.0] * 20 + [95.0, 91.0, 87.0, 79.0, 78.0, 89.0],
                "close": closes,
                "volume": [100.0] * 23 + [200.0, 200.0, 150.0],
            }
        )
        second = first.copy()
        second["symbol"] = "SECOND.SH"
        second[["open", "high", "low", "close"]] *= 0.5
        # 交错并打乱股票数据，确认 shift/rolling 不会跨股票或依赖输入顺序。
        bars = pd.concat([first, second]).sample(frac=1, random_state=7)

        reference_parts = []
        config = StrategyConfig()
        for _, symbol_bars in bars.groupby("symbol", sort=False, dropna=False):
            result = symbol_bars.sort_values("date").copy()
            result = calculate_indicators(result, config)
            result = calculate_panic_signal(result, config)
            result = calculate_reversal_signal(result, config)
            result = calculate_confirmed_signal(result)
            reference_parts.append(result)
        reference = (
            pd.concat(reference_parts)
            .sort_values(["symbol", "date"])
            .reset_index(drop=True)
        )

        actual = run_panic_reversal_strategy(bars)

        pd.testing.assert_frame_equal(actual, reference)

    def test_returns_latest_confirmed_signal(self) -> None:
        closes = [100.0] * 20 + [96.0, 92.0, 88.0, 80.0, 90.0, 95.0]
        daily_bars = pd.DataFrame(
            {
                "symbol": "TEST.SZ",
                "trade_date": pd.date_range("2026-07-01", periods=26),
                "open": [100.0] * 20 + [100.0, 96.0, 92.0, 88.0, 80.0, 90.0],
                "high": [101.0] * 20 + [101.0, 97.0, 93.0, 89.0, 91.0, 96.0],
                "low": [99.0] * 20 + [95.0, 91.0, 87.0, 79.0, 78.0, 89.0],
                "close": closes,
                "volume": [100.0] * 23 + [200.0, 200.0, 150.0],
            }
        )
        stocks = pd.DataFrame(
            {
                "symbol": ["TEST.SZ"],
                "name": ["测试股份"],
                "exchange": ["SZ"],
            }
        )
        hot_stocks = pd.DataFrame({"symbol": ["TEST.SZ"], "hot_value": [1000.0]})

        result = execute_strategy(
            "panic-reversal",
            stocks=stocks,
            daily_bars=daily_bars,
            hot_stocks=hot_stocks,
            stock_daily_basic=FakeStockDailyBasicRepository().get_table_data(),
        )

        self.assertEqual(result.columns.tolist(), RESULT_COLUMNS)
        self.assertEqual(result["symbol"].tolist(), ["TEST.SZ"])
        self.assertEqual(result.loc[0, "latest_date"], pd.Timestamp("2026-07-26"))
        self.assertTrue(result.loc[0, "confirmed_signal"])
        self.assertEqual(result.loc[0, "signal_stage"], "确认")
        self.assertEqual(result.loc[0, "hot_rank"], 1)

        payload = format_strategy_result("panic-reversal", result, limit=100)
        self.assertEqual(payload["trade_date"], "2026-07-26")
        self.assertEqual(payload["strategy"]["id"], "panic-reversal")


if __name__ == "__main__":
    unittest.main()
