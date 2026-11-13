"""批量历史指标与原逐日扫描保持一致，且不使用未来快照。"""

import unittest

import numpy as np
import pandas as pd

from backend.quant.signal.history import scan_signal_range
from backend.quant.stock.universe import build_snapshot_lookup
from backend.quant.signal.patterns.today_volume_breakout import TodayVolumeBreakoutPattern


def market_data(stock_count=8):
    days = pd.bdate_range('2026-04-01', periods=150)
    frames = []
    for index in range(stock_count):
        volume = np.full(len(days), 100.0)
        volume[10 + index % 5::13] = 400
        frame = pd.DataFrame({
            'symbol': f'S{index:04}', 'trade_date': days,
            'close': 10 + np.arange(len(days)) * .1, 'volume': volume,
        })
        if index == 1:
            frame.loc[25:110, 'volume'] = 0
        if index == 2:
            frame = frame.drop(index=range(90, 110))  # 停牌
        frames.append(frame)
    bars = pd.concat(frames, ignore_index=True)
    stocks, basics, hot = [], [], []
    for day_index in (0, 100, 149):
        for index in range(stock_count):
            symbol = f'S{index:04}'
            stocks.append(dict(symbol=symbol, trade_date=days[day_index],
                               name='ST样例' if index == 3 and day_index >= 100 else symbol,
                               market='主板', exchange='SH'))
            basics.append(dict(symbol=symbol, trade_date=days[day_index],
                               market_cap=5e9 if index == 4 and day_index >= 100 else 2e10))
            if index != 5:
                hot.append(dict(symbol=symbol, trade_date=days[day_index], rank=index + 1))
    return dict(daily_bars=bars, historical_stocks=pd.DataFrame(stocks),
                historical_basic=pd.DataFrame(basics), historical_hot=pd.DataFrame(hot),
                start_date=days[85], end_date=days[145])


def reference_scan(inputs):
    pattern = TodayVolumeBreakoutPattern()
    bars = inputs['daily_bars'].sort_values('trade_date', kind='stable')
    snapshots = [build_snapshot_lookup(inputs[key]) for key in
                 ('historical_stocks', 'historical_basic', 'historical_hot')]
    results = []
    days = sorted(bars.loc[bars.trade_date.between(inputs['start_date'], inputs['end_date']), 'trade_date'].unique())
    for day in days:
        window = bars[bars.trade_date <= day]
        result = pattern.scan(*(snapshot(day) for snapshot in snapshots), window)
        result = result[result.latest_date == day]
        if not result.empty:
            results.append(result)
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def normalized(frame):
    return frame.sort_values(['latest_date', 'symbol']).reset_index(drop=True)


class VolumeBreakoutHistoryTests(unittest.TestCase):
    def test_first_scan_day_uses_valid_bars_before_long_invalid_gap(self):
        inputs = market_data(stock_count=1)
        bars = inputs['daily_bars'].copy()
        bars['volume'] = 100.0
        bars.loc[10:130, 'volume'] = 0
        bars.loc[131, 'volume'] = 400
        # 连续 121 条无效行情不应挤掉更早的 10 个有效交易日。
        # 重复记录也不能占用前置交易日名额，输入顺序不影响结果。
        inputs['daily_bars'] = pd.concat([bars, bars.iloc[[9]]], ignore_index=True).sample(frac=1, random_state=42)
        inputs['start_date'] = inputs['end_date'] = bars.loc[131, 'trade_date']
        actual = scan_signal_range('today_volume_breakout', **inputs)
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual.iloc[0]['latest_date'], inputs['end_date'])
        self.assertEqual(actual.iloc[0]['previous_10d_avg_volume'], 100)
        self.assertEqual(actual.iloc[0]['volume_ratio'], 4)

    def test_matches_daily_scan_with_invalid_bars_suspension_and_snapshot_changes(self):
        inputs = market_data()
        expected = reference_scan(inputs)
        self.assertGreater(len(expected), 0)
        actual = scan_signal_range('today_volume_breakout', **inputs)
        pd.testing.assert_frame_equal(normalized(actual), normalized(expected), check_dtype=False)

    def test_future_bars_and_snapshots_do_not_change_results(self):
        inputs = market_data()
        expected = scan_signal_range('today_volume_breakout', **inputs)
        for key in ('daily_bars', 'historical_stocks', 'historical_basic', 'historical_hot'):
            frame = inputs[key]
            inputs[key] = frame[frame.trade_date <= inputs['end_date']]
        actual = scan_signal_range('today_volume_breakout', **inputs)
        pd.testing.assert_frame_equal(actual, expected)

    def test_empty_and_single_day_ranges(self):
        inputs = market_data()
        inputs['start_date'] = inputs['end_date'] = inputs['daily_bars'].trade_date.sort_values().unique()[140]
        pd.testing.assert_frame_equal(
            normalized(scan_signal_range('today_volume_breakout', **inputs)),
            normalized(reference_scan(inputs)), check_dtype=False,
        )
        inputs['daily_bars'] = inputs['daily_bars'].iloc[:0]
        self.assertTrue(scan_signal_range('today_volume_breakout', **inputs).empty)
