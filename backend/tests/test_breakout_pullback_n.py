"""三阶段形态回归：信号只在缩量回调后的放量大阳线触发。"""

import unittest
from dataclasses import replace

import pandas as pd

from backend.quant.signal.patterns.breakout_pullback_n import (
    DEFAULT_CONFIG,
    SIGNAL_COLUMNS,
    detect_strong_breakout_pullback,
)


def pattern():
    # 更早存在高点，也应允许后续强势上涨构成形态。
    rows = [(17, 17.2, 16.8, 17, 100)] * 20
    rows += [(10, 10.2, 9.8, 10, 100)]
    rows += [
        (10, 11.2, 9.9, 11, 1000),
        (11, 12.2, 10.9, 12, 1000),
        (12, 13.2, 11.9, 13, 1000),
        (13, 14.2, 12.9, 14, 1000),
        (14, 15.2, 13.9, 15, 1000),
    ]
    rows += [
        (15, 15.1, 14.3, 14.5, 500),
        (14.5, 14.6, 13.6, 13.8, 450),
        (13.8, 14, 13.2, 13.5, 400),
        (13.5, 13.9, 13.3, 13.7, 350),
        (13.7, 13.8, 13.1, 13.4, 300),
        (13.4, 13.7, 13.2, 13.5, 300),
        # 收于前高下方，但突破最近三根 K 线，放量大阳。
        (13.5, 14.9, 13.4, 14.8, 1200),
    ]
    result = pd.DataFrame(rows, columns=['open', 'high', 'low', 'close', 'volume'])
    return result.assign(symbol='TEST', date=pd.date_range('2026-01-01', periods=len(rows)))


class BreakoutPullbackTests(unittest.TestCase):
    def test_matches_below_previous_peak_and_older_high(self):
        result = detect_strong_breakout_pullback(pattern())
        self.assertEqual(len(result), 1)
        self.assertEqual(list(result), SIGNAL_COLUMNS)
        self.assertEqual(result.iloc[0]['date'], pattern().iloc[-1]['date'])
        self.assertLess(result.iloc[0]['close'], 15.2)

    def test_variable_rise_duration(self):
        for days in (3, 10, 25):
            with self.subTest(days=days):
                original = pattern()
                rise = []
                for i in range(days):
                    opening = 10 + 5 * i / days
                    close = 10 + 5 * (i + 1) / days
                    rise.append(dict(open=opening, high=close + 0.2,
                                     low=opening - 0.1, close=close, volume=1000))
                bars = pd.concat([original.iloc[:21], pd.DataFrame(rise), original.iloc[26:]], ignore_index=True)
                bars['symbol'] = 'TEST'
                bars['date'] = pd.date_range('2026-01-01', periods=len(bars))
                self.assertEqual(len(detect_strong_breakout_pullback(bars)), 1)
                if days == 25:
                    short_window = replace(DEFAULT_CONFIG, max_breakout_days=10)
                    self.assertTrue(detect_strong_breakout_pullback(bars, short_window).empty)

    def test_long_pullback_finishes_on_large_bullish_candle(self):
        original = pattern()
        consolidation = pd.concat([original.iloc[[31]]] * 27, ignore_index=True)
        bars = pd.concat([original.iloc[:-1], consolidation, original.iloc[[-1]]], ignore_index=True)
        bars["date"] = pd.date_range("2026-01-01", periods=len(bars))
        result = detect_strong_breakout_pullback(bars, start_date=bars["date"].iloc[26])
        self.assertEqual(result["date"].tolist(), [bars["date"].iloc[-1]])

    def test_volume_expands_against_end_of_pullback(self):
        bars = pattern()
        # 回调前几天较活跃，最后五天明显缩量。
        bars.loc[26:31, "volume"] = [1350, 400, 400, 400, 400, 400]
        bars.loc[32, "volume"] = 850
        result = detect_strong_breakout_pullback(bars)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.iloc[0]["volume_ratio"], 850 / 400)

        # 末段量能也不再缩小时，同样的确认 K 线不足以放量。
        bars.loc[26:31, "volume"] = 550
        self.assertTrue(detect_strong_breakout_pullback(bars).empty)

    def test_only_triggers_on_confirmation(self):
        self.assertTrue(detect_strong_breakout_pullback(pattern().iloc[:-1]).empty)

    def test_rejects_false_patterns(self):
        cases = {}
        bars = pattern()
        bars.loc[len(bars)-1, ['open', 'high', 'low', 'close']] = [14.4, 14.9, 14.3, 14.8]
        cases['gap_up_small_body'] = bars
        bars = pattern()
        bars.loc[len(bars)-1, 'volume'] = 500
        cases['no_confirmation_volume'] = bars
        bars = pattern()
        bars.loc[26:31, 'volume'] = 1100
        cases['no_volume_contraction'] = bars
        bars = pattern()
        bars.loc[26:31, ['open', 'high', 'low', 'close']] = [15, 15.1, 14.9, 15]
        bars.loc[32, ['open', 'high', 'low', 'close']] = [15, 16.2, 14.9, 16]
        cases['flat_without_pullback'] = bars
        bars = pattern()
        bars.loc[28, 'low'] = 10.1
        cases['erased_advance'] = bars
        bars = pattern()
        bars.loc[32, 'high'] = 18
        cases['long_upper_wick'] = bars
        bars = pattern()
        bars.loc[21:25, 'volume'] = 100
        cases['low_volume_rise'] = bars
        for name, bars in cases.items():
            with self.subTest(name=name):
                self.assertTrue(detect_strong_breakout_pullback(bars).empty)

    def test_invalid_bars_are_not_removed_to_stitch_pattern(self):
        for value in (0, float('nan'), float('inf')):
            with self.subTest(value=value):
                bars = pattern().astype({'volume': float})
                bars.loc[29, 'volume'] = value
                self.assertTrue(detect_strong_breakout_pullback(bars).empty)

    def test_sorting_and_latest_market_date(self):
        bars = pattern()
        self.assertEqual(len(detect_strong_breakout_pullback(bars.sample(frac=1, random_state=1))), 1)
        newer = bars.iloc[[-1]].assign(symbol='NEW', date=bars.date.max() + pd.Timedelta(days=1))
        self.assertTrue(detect_strong_breakout_pullback(pd.concat([bars, newer])).empty)

    def test_short_config_does_not_require_five_day_return_history(self):
        bars = pd.DataFrame([
            (10, 10.1, 9.9, 10, 1000),
            (10, 15.2, 9.9, 15, 1000),
            (15, 15.1, 13.3, 13.8, 300),
            (13.8, 15.4, 13.7, 15.3, 1200),
        ], columns=['open', 'high', 'low', 'close', 'volume'])
        bars = bars.assign(symbol='TEST', date=pd.date_range('2026-01-01', periods=4))
        config = replace(DEFAULT_CONFIG, min_breakout_days=1, min_pullback_days=1)
        self.assertEqual(len(detect_strong_breakout_pullback(bars, config)), 1)

    def test_window_and_short_input(self):
        bars = pattern()
        self.assertEqual(len(detect_strong_breakout_pullback(bars.tail(DEFAULT_CONFIG.max_required_days))), 1)
        self.assertTrue(detect_strong_breakout_pullback(bars.iloc[:5]).empty)


if __name__ == '__main__':
    unittest.main()
