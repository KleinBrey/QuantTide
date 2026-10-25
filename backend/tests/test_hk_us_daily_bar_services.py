"""直接验证港美股 Service 的日 K 同步，不依赖脚本或外部行情。"""

import threading
import unittest
from unittest.mock import Mock

from backend.app.services import HKMarketService, USMarketService


class MarketDailyBarServiceTests(unittest.TestCase):
    def services(self):
        for service_class, market, symbol in [
            (HKMarketService, 'HK', '00700.HK'),
            (USMarketService, 'US', 'AAPL'),
        ]:
            provider = Mock()
            repository = Mock()
            watchlists = Mock()
            watchlists.get_pool.return_value = {'id': 7}
            watchlists.list_items.return_value = [{'symbol': symbol}]
            service = service_class(
                yfinance_provider=provider,
                daily_repository=repository,
                watchlist_repository=watchlists,
            )
            yield service, market, symbol, provider, repository, watchlists

    def test_sync_filters_volume_writes_on_caller_thread_and_reloads_pool(self):
        for service, market, symbol, provider, repository, watchlists in self.services():
            with self.subTest(market=market):
                caller_thread = threading.get_ident()
                now_ms = 1773100800000
                row = dict(date_ms=now_ms, open_price=10, high_price=12,
                           low_price=9, close_price=11, volume=100)

                def fetch(*args, **kwargs):
                    self.assertNotEqual(threading.get_ident(), caller_thread)
                    return {'data': {'item': [row, {**row, 'volume': 0}, {**row, 'volume': None}]}}

                def write(rows):
                    self.assertEqual(threading.get_ident(), caller_thread)
                    self.assertEqual(rows.symbol.tolist(), [symbol])
                    self.assertEqual(rows.volume.tolist(), [100])
                    self.assertEqual(rows.source.tolist(), ['YFinance'])
                    self.assertTrue(rows.amount.isna().all())
                    return len(rows)

                provider.fetch_historical.side_effect = fetch
                repository.upsert_daily_bars.side_effect = write
                result = service.update_daily_bars(3, 2, 0, now_ms=now_ms)
                self.assertEqual(result, {'stocks': 1, 'rows': 1})
                watchlists.get_pool.assert_called_once_with(market)
                provider.fetch_historical.assert_called_once_with(
                    symbol, now_ms - 3 * 86400000, now_ms, interval='1d', adjust='forward',
                )
                watchlists.list_items.return_value = []
                provider.reset_mock()
                repository.reset_mock()
                self.assertEqual(service.update_daily_bars(3, 1, 0),
                                 {'stocks': 0, 'rows': 0})
                provider.fetch_historical.assert_not_called()
                repository.upsert_daily_bars.assert_not_called()

    def test_empty_data_and_invalid_parameters_do_not_write(self):
        for service, market, _, provider, repository, _ in self.services():
            with self.subTest(market=market):
                for kwargs in [dict(lookback_days=0), dict(lookback_days=-1),
                               dict(max_workers=0), dict(request_interval=-1)]:
                    with self.assertRaises(ValueError):
                        service.update_daily_bars(**kwargs)
                provider.fetch_historical.assert_not_called()
                provider.fetch_historical.return_value = {'data': {'item': []}}
                self.assertEqual(service.update_daily_bars(3, 1, 0),
                                 {'stocks': 1, 'rows': 0})
                repository.upsert_daily_bars.assert_not_called()

    def test_fetch_format_and_write_failures_preserve_successful_rows(self):
        for service, market, symbol, provider, repository, watchlists in self.services():
            with self.subTest(market=market):
                watchlists.list_items.return_value = [
                    {'symbol': value} for value in ['FETCH', 'FORMAT', 'WRITE', symbol]
                ]
                written_symbols = []

                def fetch(value, *args, **kwargs):
                    if value == 'FETCH':
                        raise RuntimeError('接口失败')
                    if value == 'FORMAT':
                        return {'data': {'item': [{'date_ms': 1773100800000}]}}
                    return {'data': {'item': [dict(
                        date_ms=1773100800000, open_price=10, high_price=12,
                        low_price=9, close_price=11, volume=100,
                    )]}}

                def write(rows):
                    if rows.symbol.iloc[0] == 'WRITE':
                        raise RuntimeError('写入失败')
                    written_symbols.extend(rows.symbol.tolist())
                    return len(rows)

                provider.fetch_historical.side_effect = fetch
                repository.upsert_daily_bars.side_effect = write
                market_name = '港股' if market == 'HK' else '美股'
                with self.assertRaisesRegex(
                    RuntimeError,
                    f'^{market_name}日 K 未完整同步，已写入 1 条，失败股票：FETCH, FORMAT, WRITE$',
                ):
                    service.update_daily_bars(3, 2, 0)
                self.assertEqual(provider.fetch_historical.call_count, 4)
                self.assertEqual(written_symbols, [symbol])

    def test_all_symbols_fail_without_writing(self):
        for service, market, symbol, provider, repository, _ in self.services():
            with self.subTest(market=market):
                provider.fetch_historical.side_effect = RuntimeError('接口失败')
                with self.assertRaises(RuntimeError) as error:
                    service.update_daily_bars(3, 1, 0)
                market_name = '港股' if market == 'HK' else '美股'
                self.assertEqual(
                    str(error.exception),
                    f'{market_name}日 K 未完整同步，已写入 0 条，失败股票：{symbol}',
                )
                repository.upsert_daily_bars.assert_not_called()

    def test_missing_dependencies_raise_clear_error(self):
        for service_class in [HKMarketService, USMarketService]:
            with self.subTest(service=service_class.__name__), self.assertRaisesRegex(RuntimeError, '未配置'):
                service_class().update_daily_bars()


if __name__ == '__main__':
    unittest.main()
