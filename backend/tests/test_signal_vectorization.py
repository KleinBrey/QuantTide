"""批量指标对照逐窗口公式，并验证历史扫描的快照和时间边界。"""

import unittest

import numpy as np
import pandas as pd

from backend.quant.signal.history import scan_signal_range
from backend.quant.signal.registry import SIGNAL_PATTERNS
from backend.quant.stock.universe import build_snapshot_lookup
from backend.quant.signal.registry import execute_signal
from backend.tests.test_volume_breakout_history import market_data

WINDOW_PATTERNS = {key: SIGNAL_PATTERNS[key] for key in (
    'today_volume_breakout', 'recent_volume_breakout', 'today_emotion_reversal',
    'panic-reversal', 'second-rebound-short',
)}


def bars_fixture():
    rng = np.random.default_rng(42)
    frames = []
    for symbol in ('A', 'B', 'C'):
        close = np.round(10 * np.exp(np.cumsum(rng.normal(0, .035, 150))), 2)
        opening = np.round(close * rng.uniform(.94, 1.04, len(close)), 2)
        frames.append(pd.DataFrame(dict(
            symbol=symbol, trade_date=pd.bdate_range('2026-01-01', periods=len(close)),
            open=opening, close=close, high=np.maximum(close, opening) + .1,
            low=np.minimum(close, opening) - .1, volume=rng.integers(100, 1000, len(close)),
            amount=300_000,
        )))
    bars = pd.concat(frames, ignore_index=True)
    bars.loc[30:115, 'volume'] = 0
    bars.loc[160:163, 'close'] = np.nan
    bars.loc[330:332, 'open'] = 0
    return bars.drop(index=range(190, 200))  # 停牌不补行情


def scalar_indicators(pattern, key, bars):
    """测试用逐股票、逐日基准：直接对当前窗口求均值和涨幅。"""
    rows = []
    cleaner = getattr(pattern, 'filter_daily_bars', None) or pattern.clean_daily_bars
    config = pattern.config
    for symbol, raw in bars.groupby('symbol', sort=False):
        raw = raw.sort_values('trade_date')
        for index in range(len(raw)):
            window = cleaner(raw.iloc[:index + 1], pd.Series([symbol]))
            window = window.drop_duplicates('trade_date', keep='last').tail(config.required_trading_days)
            if len(window) < config.required_trading_days or window.iloc[-1].trade_date != raw.iloc[index].trade_date:
                continue
            row = dict(symbol=symbol, latest_date=window.iloc[-1].trade_date, latest_close=window.iloc[-1].close)
            if key == 'today_emotion_reversal':
                row.update(latest_open=window.iloc[-1].open,
                           previous_1d_pct=window.iloc[-2].close / window.iloc[-3].close - 1,
                           latest_open_gap_pct=window.iloc[-1].open / window.iloc[-2].close - 1,
                           latest_1d_pct=window.iloc[-1].close / window.iloc[-2].close - 1)
            else:
                recent = window.iloc[-config.recent_volume_days:]
                previous = window.iloc[:-config.recent_volume_days]
                average = previous.volume.mean()
                if key == 'today_volume_breakout':
                    row.update(latest_volume=recent.volume.iloc[-1], previous_10d_avg_volume=average,
                               volume_ratio=recent.volume.iloc[-1] / average,
                               latest_1d_pct=window.close.iloc[-1] / previous.close.iloc[-1] - 1)
                elif key == 'recent_volume_breakout':
                    row.update(recent_5d_avg_volume=recent.volume.mean(), previous_20d_avg_volume=average,
                               volume_ratio=recent.volume.mean() / average,
                               latest_5d_pct=window.close.iloc[-1] / window.close.iloc[-6] - 1,
                               latest_1d_pct=window.close.iloc[-1] / window.close.iloc[-2] - 1)
                else:
                    row.update(ma5=window.close.tail(5).mean(), ma10=window.close.tail(10).mean(),
                               ma20=window.close.tail(20).mean(), recent_3d_low=recent.low.min(),
                               recent_3d_avg_volume=recent.volume.mean(), previous_20d_avg_volume=average,
                               volume_ratio=recent.volume.mean() / average)
            rows.append(row)
    return pd.DataFrame(rows)


def normalize(frame):
    if frame.empty:
        return pd.DataFrame()
    return frame.sort_values(['latest_date', 'symbol']).reset_index(drop=True)


class SignalVectorizationTests(unittest.TestCase):
    def test_batch_indicators_match_scalar_windows(self):
        bars = bars_fixture()
        for key, factory in WINDOW_PATTERNS.items():
            if key == 'second-rebound-short':
                continue  # 本身已有向量公式，另测批量/逐日入口。
            with self.subTest(signal=key):
                pattern = factory()
                actual = pattern.calculate_range_indicators(bars)
                expected = scalar_indicators(pattern, key, bars)
                pd.testing.assert_frame_equal(
                    normalize(actual), normalize(expected[actual.columns]),
                    check_dtype=False, check_exact=True,
                )
                self.assertTrue(pattern.calculate_range_indicators(bars.iloc[:0]).empty)
                self.assertTrue(pattern.calculate_range_indicators(bars.iloc[:1]).empty)

    def test_history_matches_daily_calls_and_excludes_future(self):
        inputs = market_data()
        bars = inputs['daily_bars']
        # 保留历史快照变化，并补齐各形态需要的 K 线字段。
        inputs['daily_bars'] = bars.assign(open=bars.close * .97, high=bars.close * 1.02,
                                          low=bars.close * .95, amount=300_000)
        bars = inputs['daily_bars'].sort_values('trade_date', kind='stable')
        snapshots = {name: build_snapshot_lookup(inputs['historical_' + name]) for name in ('stocks', 'basic', 'hot')}
        days = sorted(bars.loc[bars.trade_date.between(inputs['start_date'], inputs['end_date']), 'trade_date'].unique())
        for key in WINDOW_PATTERNS:
            with self.subTest(signal=key):
                results = []
                for day in days:
                    result = execute_signal(key, daily_bars=bars[bars.trade_date <= day],
                                            latest_stocks=snapshots['stocks'](day), latest_basic=snapshots['basic'](day),
                                            latest_hot=snapshots['hot'](day))
                    if not result.empty:
                        results.append(result[result.latest_date == day])
                expected = pd.concat(results, ignore_index=True) if results else pd.DataFrame()
                actual = scan_signal_range(key, **inputs)
                pd.testing.assert_frame_equal(normalize(actual), normalize(expected), check_dtype=False)
                truncated = {k: v[v.trade_date <= inputs['end_date']] if isinstance(v, pd.DataFrame) else v
                             for k, v in inputs.items()}
                pd.testing.assert_frame_equal(scan_signal_range(key, **truncated), actual)
