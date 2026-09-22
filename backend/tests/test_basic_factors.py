from __future__ import annotations

import unittest

import pandas as pd

from backend.quant.factor import (
    FACTOR_COLUMNS,
    calculate_basic_factors,
)


def make_bars(symbol: str = "TEST") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": pd.date_range("2026-01-01", periods=25, freq="D"),
            "close": range(100, 125),
            "volume": range(10, 35),
        }
    )


class BasicFactorsTests(unittest.TestCase):
    def test_calculates_six_factors(self) -> None:
        bars = make_bars()
        result = calculate_basic_factors(bars)

        self.assertAlmostEqual(result.loc[1, "return_1d"], 101 / 100 - 1)
        self.assertAlmostEqual(result.loc[5, "momentum_5d"], 105 / 100 - 1)
        self.assertAlmostEqual(result.loc[20, "momentum_20d"], 120 / 100 - 1)
        self.assertAlmostEqual(result.loc[4, "volume_ratio_5d"], 14 / 12)
        self.assertAlmostEqual(
            result.loc[19, "distance_ma20"], 119 / 109.5 - 1
        )

        expected_volatility = bars["close"].pct_change().rolling(20).std().iloc[20]
        self.assertAlmostEqual(result.loc[20, "volatility_20d"], expected_volatility)

    def test_incomplete_windows_are_missing(self) -> None:
        result = calculate_basic_factors(make_bars())

        self.assertTrue(pd.isna(result.loc[0, "return_1d"]))
        self.assertTrue(pd.isna(result.loc[4, "momentum_5d"]))
        self.assertTrue(pd.isna(result.loc[19, "momentum_20d"]))
        self.assertTrue(pd.isna(result.loc[3, "volume_ratio_5d"]))
        self.assertTrue(pd.isna(result.loc[19, "volatility_20d"]))
        self.assertTrue(pd.isna(result.loc[18, "distance_ma20"]))

    def test_symbols_are_calculated_independently(self) -> None:
        first = make_bars("FIRST")
        second = make_bars("SECOND")
        second["close"] = second["close"] * 10
        mixed = pd.concat([first, second], ignore_index=True).sample(
            frac=1, random_state=7
        )

        result = calculate_basic_factors(mixed)
        first_result = result.loc[result["symbol"] == "FIRST", FACTOR_COLUMNS]
        second_result = result.loc[result["symbol"] == "SECOND", FACTOR_COLUMNS]

        pd.testing.assert_frame_equal(
            first_result.reset_index(drop=True),
            second_result.reset_index(drop=True),
        )

    def test_future_bars_do_not_change_existing_factors(self) -> None:
        bars = make_bars()
        prefix_result = calculate_basic_factors(bars.iloc[:22])
        full_result = calculate_basic_factors(bars)

        pd.testing.assert_frame_equal(
            prefix_result[FACTOR_COLUMNS],
            full_result.iloc[:22][FACTOR_COLUMNS].reset_index(drop=True),
        )

    def test_input_dataframe_is_not_modified(self) -> None:
        bars = make_bars()
        original = bars.copy(deep=True)

        calculate_basic_factors(bars)

        pd.testing.assert_frame_equal(bars, original)

    def test_missing_column_has_clear_error(self) -> None:
        bars = make_bars().drop(columns="volume")

        with self.assertRaisesRegex(ValueError, "volume"):
            calculate_basic_factors(bars)


if __name__ == "__main__":
    unittest.main()
