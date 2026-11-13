"""所有策略使用同一区间接口，调度层不限制策略所需的前置行情。"""

import unittest
from dataclasses import replace

import pandas as pd

from backend.quant.signal.history import scan_signal_range
from backend.quant.signal.registry import SIGNAL_PATTERNS, signal_list
from backend.quant.signal.patterns.second_rebound_short import DEFAULT_CONFIG, SecondReboundShortPattern, run_signal
from backend.quant.stock.universe import build_snapshot_lookup
from backend.tests.test_volume_breakout_history import market_data


class SignalRangeInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.inputs = market_data()
        bars = self.inputs['daily_bars']
        self.inputs['daily_bars'] = bars.assign(open=bars.close * .97, high=bars.close * 1.02,
                                               low=bars.close * .95, amount=300_000)
        self.dates = pd.DatetimeIndex(bars.trade_date.unique()).sort_values()
        self.days = self.dates[self.dates.to_series().between(self.inputs['start_date'], self.inputs['end_date']).to_numpy()]

    def test_all_registered_strategies_accept_same_keywords_and_sparse_dates(self):
        self.assertEqual(set(SIGNAL_PATTERNS), {item['id'] for item in signal_list()})
        data = {k: v for k, v in self.inputs.items() if k not in ('start_date', 'end_date')}
        for key, factory in SIGNAL_PATTERNS.items():
            with self.subTest(signal=key):
                pattern = factory()
                result = pattern.scan_range(trade_dates=self.days, **data)
                pd.testing.assert_frame_equal(result, scan_signal_range(key, **self.inputs))
                sparse = pattern.scan_range(trade_dates=iter(self.days[::3]), **data)
                if not sparse.empty:
                    column = 'confirm_date' if 'confirm_date' in sparse else 'latest_date'
                    self.assertTrue(sparse[column].isin(self.days[::3]).all())
                self.assertTrue(pattern.scan_range(trade_dates=[], **data).empty)

    def test_invalid_dates_are_rejected(self):
        for start, end in [(self.days[-1], self.days[0]), (None, self.days[-1])]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                scan_signal_range('today_volume_breakout', **{**self.inputs, 'start_date': start, 'end_date': end})

    def test_snapshot_lookup_uses_complete_past_snapshot(self):
        history = pd.DataFrame({'trade_date': pd.to_datetime(['2026-01-01', '2026-01-01', '2026-01-03']),
                                'symbol': ['A', 'B', 'B']})
        lookup = build_snapshot_lookup(history)
        self.assertTrue(lookup(pd.Timestamp('2025-12-31')).empty)
        self.assertEqual(lookup(pd.Timestamp('2026-01-02')).symbol.tolist(), ['A', 'B'])
        self.assertEqual(lookup(pd.Timestamp('2026-01-03')).symbol.tolist(), ['B'])

    def test_strategy_can_require_more_than_eighty_prior_bars(self):
        # 较早前高在 100 日窗口内、80 日窗口外；调度层不得提前截掉。
        days = pd.bdate_range('2026-01-01', periods=120)
        bars = pd.DataFrame(dict(symbol='A', trade_date=days, open=9.5, high=9.8,
                                 low=9.4, close=9.5, volume=100., amount=300_000.))
        bars.loc[25, 'high'] = 10.
        bars.loc[105, 'low'] = 8.5
        bars.loc[118, ['open', 'high', 'low', 'close', 'volume']] = [9.5, 10., 9., 9.2, 300.]
        bars.loc[119, ['open', 'high', 'low', 'close', 'volume']] = [9.2, 9.3, 8.5, 8.7, 150.]
        stocks = pd.DataFrame([dict(symbol='A', trade_date=days[0], name='A', market='主板', exchange='SH')])
        basic = stocks[['symbol', 'trade_date']].assign(market_cap=2e10)
        hot = stocks[['symbol', 'trade_date']].assign(rank=1)
        config = replace(DEFAULT_CONFIG, peak_lookback_days=100)
        expected = run_signal(latest_stocks=stocks, daily_bars=bars, latest_hot=hot, latest_basic=basic, config=config)
        self.assertEqual(len(expected), 1)
        actual = SecondReboundShortPattern(config).scan_range(
            [days[-1]], stocks, bars.sample(frac=1, random_state=42), hot, basic,
        )
        pd.testing.assert_frame_equal(actual, expected)
