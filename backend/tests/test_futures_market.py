"""用临时库验证主力筛选、行情入库和自选分组。"""
import tempfile
import threading
import unittest
from datetime import date, datetime
from functools import partial
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from backend.app.database import FuturesDuckDBDatabase, SQLiteDatabase
from backend.app.repository.futures_market_db import FuturesMarketRepository
from backend.app.repository.watchlist import WatchlistRepository
from backend.app.services.futures_market_service import FuturesMarketService
from backend.app.services.watchlist_service import WatchlistService
from backend.app.utils.concurrency import concurrent_requests


class FuturesMarketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db = FuturesDuckDBDatabase(Path(self.temp.name) / 'futures.duckdb')
        db.initialize()
        self.repo = FuturesMarketRepository(db)
        self.app_db = SQLiteDatabase(Path(self.temp.name) / 'app.sqlite')
        self.app_db.initialize()
        self.watchlists = WatchlistRepository(self.app_db)
        self.pool = self.watchlists.ensure_default_pool('FUTURES')
        self.provider = Mock()
        self.provider.fetch_futures_trade_dates.return_value = [date(2026, 10, 29), date(2026, 10, 30)]
        self.provider.fetch_futures_mapping.side_effect = lambda day: pd.DataFrame([
            dict(ts_code='RB.SHF', trade_date=day.strftime('%Y%m%d'), mapping_ts_code='RB2701.SHF'),
        ])
        self.service = FuturesMarketService(self.provider, self.repo, self.watchlists)

    def test_latest_update_time_returns_none_for_empty_daily_bars_and_max_for_data(self):
        self.assertIsNone(self.repo.get_latest_update_time())
        self.repo.upsert_daily_bars(pd.DataFrame([
            dict(symbol='RB.SHF', trade_date=day, open=1, high=2, low=1,
                 close=2, volume=3, amount=4, settle=2, open_interest=5)
            for day in ('2026-10-29', '2026-10-30')
        ]))
        with self.repo.db.connection() as connection:
            connection.execute("""
                UPDATE daily_bars SET update_time = CASE
                    WHEN trade_date = '2026-10-29' THEN TIMESTAMP '2026-10-31 10:30:00'
                    ELSE TIMESTAMP '2026-10-31 09:00:00'
                END
            """)
        self.assertEqual(self.repo.get_latest_update_time(), datetime(2026, 10, 31, 10, 30))

    def test_main_contract_search_and_daily_upsert(self):
        self.repo.upsert_contracts(pd.DataFrame([dict(
            symbol='OLD.SHF', name='旧品种主力', exchange='SHFE', code='OLD',
            main_symbol='OLD2612.SHF', main_name='旧品种2612',
        )]))
        self.watchlists.add_item(self.pool['id'], 'FUTURES', 'OLD.SHF')
        custom = self.watchlists.create_group('关注', None)
        self.watchlists.add_item(custom['id'], 'FUTURES', 'OLD.SHF')
        kept = self.watchlists.add_item(custom['id'], 'US', 'AAPL')
        self.provider.fetch_futures_contracts.side_effect = lambda exchange, fut_type='2': pd.DataFrame([
            dict(ts_code='RB.SHF', name='螺纹钢主力', exchange=exchange, code='RB'),
            dict(ts_code='RB2605.SHF', name='月份合约', exchange=exchange, code='RB'),
            dict(ts_code='RBL.SHF', name='连续合约', exchange=exchange, code='RB'),
            dict(ts_code='UNMAPPED.SHF', name='无映射主力', exchange=exchange, code='UNMAPPED'),
        ] if fut_type == '2' else [
            dict(ts_code='RB2701.SHF', name='螺纹钢2701', exchange=exchange, code='RB'),
        ])
        with patch('backend.app.services.futures_market_service.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 31)
            self.service.update_contracts()
        self.provider.fetch_futures_trade_dates.assert_called_once_with(date(2026, 9, 30), date(2026, 10, 31))
        self.provider.fetch_futures_mapping.assert_called_once_with(date(2026, 10, 30))
        self.assertEqual(self.repo.list_contract_symbols(), ['RB.SHF'])
        self.assertEqual(self.watchlists.list_items(self.pool['id']), [])
        self.assertEqual(self.watchlists.list_items(custom['id']), [kept])
        with self.repo.db.connection(read_only=True) as connection:
            self.assertEqual(connection.execute('SELECT DISTINCT symbol FROM contracts').fetchall(), [('RB.SHF',)])
        service = WatchlistService(self.watchlists, None, None, None, futures_repository=self.repo)
        found = service.search('螺纹', 'FUTURES')
        self.assertEqual([row['symbol'] for row in found], ['RB.SHF'])
        self.assertEqual(found[0]['name'], '螺纹钢2701')
        self.assertEqual(found[0]['display_symbol'], 'RB2701.SHF')
        self.assertEqual(found[0]['series_name'], '螺纹钢主力')
        self.assertEqual(service.search('rb2701', 'FUTURES'), found)
        self.assertEqual(service.search('RB.SHF', 'FUTURES'), found)
        service.add_item(self.pool['id'], 'FUTURES', 'rb.shf')
        item = service.list_items(self.pool['id'])[0]
        self.assertEqual(item['symbol'], 'RB.SHF')
        self.assertEqual(item['display_symbol'], 'RB2701.SHF')
        self.provider.fetch_futures_daily.return_value = pd.DataFrame([dict(
            ts_code='RB.SHF', trade_date='20261029', open=3000, high=3100, low=2900,
            close=3050, vol=100, amount=12, settle=3040, oi=200,
        )])
        self.service.update_daily_bars(366)
        self.assertEqual(self.provider.fetch_futures_daily.call_count, 2)
        rows = self.repo.get_by_symbol_and_date_range('RB.SHF', date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.iloc[0].amount, 120000)
        self.assertEqual(rows.iloc[0].volume, 100)

    def test_contract_requests_overlap_and_only_save_after_all_succeed(self):
        caller = threading.get_ident()
        for fail in (False, True):
            with self.subTest(fail=fail):
                self.repo.upsert_contracts(pd.DataFrame([dict(
                    symbol='OLD.SHF', name='旧主力', exchange='SHFE', code='OLD',
                    main_symbol='OLD2701.SHF', main_name='旧品种2701',
                )]), replace=True)
                barrier = threading.Barrier(2)
                request_threads = []
                write_threads = []
                upsert = self.repo.upsert_contracts

                def fetch(exchange, mapping):
                    request_threads.append(threading.get_ident())
                    barrier.wait(timeout=5)
                    if fail and exchange == 'DCE':
                        raise RuntimeError('DCE 模拟请求失败')
                    symbol = 'RB.SHF' if exchange == 'SHFE' else 'M.DCE'
                    return pd.DataFrame([dict(
                        symbol=symbol, name=symbol, exchange=exchange,
                        code=symbol.split('.')[0], main_symbol=symbol,
                        main_name=symbol,
                    )])

                def save(rows, **kwargs):
                    write_threads.append(threading.get_ident())
                    self.assertEqual(rows.exchange.tolist(), ['SHFE', 'DCE'])
                    return upsert(rows, **kwargs)

                with (
                    patch('backend.app.services.futures_market_service.EXCHANGES', ('SHFE', 'DCE')),
                    patch('backend.app.services.futures_market_service.concurrent_requests',
                          partial(concurrent_requests, request_interval=0)),
                    patch.object(self.service, '_fetch_exchange_contracts', side_effect=fetch),
                    patch.object(self.repo, 'upsert_contracts', side_effect=save) as write,
                    patch.object(self.watchlists, 'retain_futures_items',
                                 wraps=self.watchlists.retain_futures_items) as retain,
                ):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, 'DCE 模拟请求失败'):
                            self.service.update_contracts()
                        write.assert_not_called()
                        retain.assert_not_called()
                        self.assertEqual(self.repo.list_contract_symbols(), ['OLD.SHF'])
                    else:
                        self.assertEqual(self.service.update_contracts(), 2)
                        self.assertEqual(write_threads, [caller])
                        retain.assert_called_once_with(['M.DCE', 'RB.SHF'])
                self.assertEqual(len(set(request_threads)), 2)
                self.assertNotIn(caller, request_threads)

    def test_daily_requests_overlap_and_partial_failure_keeps_successful_rows(self):
        for symbol in ('RB.SHF', 'AG.SHF'):
            self.watchlists.add_item(self.pool['id'], 'FUTURES', symbol)
        caller = threading.get_ident()
        barrier = threading.Barrier(2)
        request_threads = []
        write_threads = []
        upsert = self.repo.upsert_daily_bars

        def fetch(symbol, start, end):
            request_threads.append(threading.get_ident())
            barrier.wait(timeout=5)
            if symbol == 'AG.SHF':
                raise RuntimeError('模拟请求失败')
            return pd.DataFrame([dict(
                ts_code=symbol, trade_date=start.strftime('%Y%m%d'),
                open=1, high=2, low=1, close=2, vol=3, amount=4, settle=2, oi=5,
            )])

        def save(rows):
            write_threads.append(threading.get_ident())
            return upsert(rows)

        self.provider.fetch_futures_daily.side_effect = fetch
        with patch.object(self.repo, 'upsert_daily_bars', side_effect=save):
            with self.assertRaisesRegex(RuntimeError, '已写入 1 条.*AG.SHF'):
                self.service.update_daily_bars(1)
        self.assertEqual(len(set(request_threads)), 2)
        self.assertNotIn(caller, request_threads)
        self.assertEqual(write_threads, [caller])
        self.assertEqual(self.provider.fetch_futures_daily.call_count, 2)
        with self.repo.db.connection(read_only=True) as connection:
            self.assertEqual(connection.execute('SELECT symbol, amount FROM daily_bars').fetchall(),
                             [('RB.SHF', 40000)])

    def test_mapping_rollover_keeps_watchlist_identity(self):
        service = WatchlistService(self.watchlists, None, None, None, futures_repository=self.repo)
        for month in ('2701', '2705'):
            self.repo.upsert_contracts(pd.DataFrame([dict(
                symbol='RB.SHF', name='螺纹钢主力', exchange='SHFE', code='RB',
                main_symbol=f'RB{month}.SHF', main_name=f'螺纹钢{month}',
                trade_date=date(2026, 10, 29),
            )]))
            if month == '2701':
                service.add_item(self.pool['id'], 'FUTURES', 'RB.SHF')
            rows = service.list_items(self.pool['id'])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['symbol'], 'RB.SHF')
            self.assertEqual(rows[0]['name'], f'螺纹钢{month}')
            self.assertEqual(rows[0]['display_symbol'], f'RB{month}.SHF')

    def test_missing_mapping_does_not_replace_saved_metadata(self):
        self.repo.upsert_contracts(pd.DataFrame([dict(
            symbol='RB.SHF', name='螺纹钢主力', exchange='SHFE', code='RB',
            main_symbol='RB2701.SHF', main_name='螺纹钢2701',
        )]))
        self.provider.fetch_futures_mapping.side_effect = None
        self.provider.fetch_futures_mapping.return_value = pd.DataFrame()
        with self.assertRaisesRegex(RuntimeError, '暂无主力合约映射'):
            self.service.update_contracts()
        self.provider.fetch_futures_mapping.assert_called_once_with(date(2026, 10, 30))
        self.provider.fetch_futures_contracts.assert_not_called()
        service = WatchlistService(self.watchlists, None, None, None, futures_repository=self.repo)
        self.assertEqual(service.search('RB', 'FUTURES')[0]['name'], '螺纹钢2701')

    def test_empty_calendar_stops_before_fetching_mapping_or_writing(self):
        self.provider.fetch_futures_trade_dates.return_value = []
        with patch.object(self.repo, 'upsert_contracts') as save:
            with self.assertRaisesRegex(RuntimeError, '暂无期货交易日'):
                self.service.update_contracts()
            save.assert_not_called()
        self.provider.fetch_futures_mapping.assert_not_called()
        self.provider.fetch_futures_contracts.assert_not_called()

    def test_invalid_mapping_stops_before_replacing_contracts(self):
        for rows, error, message in (
            (pd.DataFrame([dict(trade_date='20261029')]), ValueError, '日期与请求日期不一致'),
            (pd.DataFrame([dict(trade_date='20261030')] * 2000), RuntimeError, '达到接口上限'),
        ):
            with self.subTest(message=message):
                self.provider.fetch_futures_mapping.side_effect = None
                self.provider.fetch_futures_mapping.return_value = rows
                with patch.object(self.repo, 'upsert_contracts') as save:
                    with self.assertRaisesRegex(error, message):
                        self.service.update_contracts()
                    save.assert_not_called()
                self.provider.fetch_futures_contracts.assert_not_called()

    def test_provider_futures_calendar_filters_sorts_and_deduplicates_dates(self):
        from backend.app.provider.tushare_provider import TushareProvider
        provider = TushareProvider.__new__(TushareProvider)
        provider.pro = Mock()
        provider.pro.fut_trade_cal.return_value = pd.DataFrame([
            dict(cal_date='20261030', is_open=1),
            dict(cal_date='20261029', is_open='1'),
            dict(cal_date='20261030', is_open=1),
            dict(cal_date='20261031', is_open=0),
            dict(cal_date='20261102', is_open=1),
            dict(cal_date='20260929', is_open=1),
        ])
        start, end = date(2026, 9, 30), date(2026, 10, 31)
        self.assertEqual(provider.fetch_futures_trade_dates(start, end),
                         [date(2026, 10, 29), date(2026, 10, 30)])
        provider.pro.fut_trade_cal.assert_called_once_with(
            is_open='1', start_date='20260930', end_date='20261031',
        )
        for empty in (None, pd.DataFrame()):
            provider.pro.fut_trade_cal.return_value = empty
            self.assertEqual(provider.fetch_futures_trade_dates(start, end), [])

    def test_current_databases_can_be_initialized_again_without_changing_data(self):
        self.repo.upsert_contracts(pd.DataFrame([dict(
            symbol='RB.SHF', name='螺纹钢主力', exchange='SHFE', code='RB',
            main_symbol='RB2701.SHF', main_name='螺纹钢2701',
            trade_date=date(2026, 10, 30),
        )]))
        self.repo.upsert_daily_bars(pd.DataFrame([dict(
            symbol='RB.SHF', trade_date=date(2026, 10, 30),
            open=3000, high=3100, low=2900, close=3050,
            volume=100, amount=120000, settle=3040, open_interest=200,
        )]))
        item = self.watchlists.add_item(self.pool['id'], 'FUTURES', 'RB.SHF')
        with self.repo.db.connection(read_only=True) as connection:
            before = {table: connection.execute(f'SELECT * FROM {table}').fetchall()
                      for table in ('contracts', 'daily_bars')}
            columns = {row[1] for row in connection.execute("PRAGMA table_info('contracts')").fetchall()}
        self.assertTrue({'code', 'main_symbol', 'main_name', 'trade_date'} <= columns)
        self.repo.db.initialize()
        self.app_db.initialize()
        with self.repo.db.connection(read_only=True) as connection:
            for table, rows in before.items():
                self.assertEqual(connection.execute(f'SELECT * FROM {table}').fetchall(), rows)
        self.assertEqual(self.watchlists.list_items(self.pool['id']), [item])

    def test_provider_converts_external_product_code(self):
        from backend.app.provider.tushare_provider import TushareProvider
        provider = TushareProvider.__new__(TushareProvider)
        provider.pro = Mock()
        provider.pro.fut_basic.return_value = pd.DataFrame([
            dict(ts_code='RB.SHF', name='螺纹钢主力', exchange='SHFE', fut_code='RB'),
        ])
        result = provider.fetch_futures_contracts('SHFE')
        self.assertEqual(result.iloc[0]['code'], 'RB')
        self.assertNotIn('fut_code', result.columns)
        provider.pro.fut_basic.assert_called_once_with(
            exchange='SHFE', fut_type='2', fields='ts_code,name,exchange,fut_code',
        )

    def test_api_search_group_and_kline(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.app.api.routes import router
        from backend.app.api import dependencies as deps
        from backend.app.main import watchlist_error_handler
        from backend.app.repository.watchlist import WatchlistError
        app = FastAPI()
        app.add_exception_handler(WatchlistError, watchlist_error_handler)
        app.include_router(router, prefix='/api')
        service = WatchlistService(self.watchlists, None, None, None, futures_repository=self.repo)
        app.dependency_overrides[deps.get_watchlist_service] = lambda: service
        for dependency in [deps.get_daily_repository, deps.get_hk_daily_repository,
                           deps.get_us_daily_repository, deps.get_futures_repository]:
            app.dependency_overrides[dependency] = lambda: self.repo
        self.repo.upsert_contracts(pd.DataFrame([dict(symbol='V_F.DCE', name='PVC月均价主力',
            exchange='DCE', code='V_F', main_symbol='V_F2612.DCE', main_name='PVC月均价2612')]))
        self.repo.upsert_daily_bars(pd.DataFrame([dict(symbol='V_F.DCE', trade_date='2026-10-29',
            open=1, high=2, low=1, close=2, volume=3, amount=4, settle=2, open_interest=5)]))
        with TestClient(app) as client:
            found = client.get('/api/watchlists/stocks/search', params={'q': 'PVC', 'market': 'FUTURES'})
            self.assertEqual(found.status_code, 200)
            self.assertEqual(found.json()[0]['symbol'], 'V_F.DCE')
            added = client.post(f"/api/watchlists/groups/{self.pool['id']}/items",
                                json={'market': 'FUTURES', 'symbol': 'v_f.dce'})
            self.assertEqual(added.status_code, 201, added.text)
            params = dict(market='futures', symbol='V_F.DCE', start='2026-10-01', end='2026-10-30')
            bars = client.get('/api/daily-bars', params=params)
            self.assertEqual(bars.status_code, 200, bars.text)
            self.assertEqual(bars.json()[0]['close'], 2)
            params['symbol'] = 'RB2610.SHF'
            # 月份合约格式虽合法，但只能从已同步的主力资料中加入自选。
            rejected = client.post(f"/api/watchlists/groups/{self.pool['id']}/items",
                                  json={'market': 'FUTURES', 'symbol': params['symbol']})
            self.assertEqual(rejected.status_code, 404)

    def test_reset_pool_includes_all_contracts_and_preserves_other_groups(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.app.api.watchlists import router
        from backend.app.api.dependencies import get_watchlist_service
        from backend.app.main import watchlist_error_handler
        from backend.app.repository.watchlist import WatchlistError

        app = FastAPI()
        app.add_exception_handler(WatchlistError, watchlist_error_handler)
        app.include_router(router)
        service = WatchlistService(self.watchlists, None, None, None, futures_repository=self.repo)
        app.dependency_overrides[get_watchlist_service] = lambda: service
        custom = self.watchlists.create_group('关注', 'FUTURES')
        custom_item = self.watchlists.add_item(custom['id'], 'FUTURES', 'RB.SHF')
        self.watchlists.add_item(self.pool['id'], 'FUTURES', 'OLD.SHF')
        with TestClient(app) as client:
            # 未同步资料时显示错误，不能把原分组意外清空。
            response = client.post('/watchlists/futures-pool/reset')
            self.assertEqual(response.status_code, 422)
            self.assertEqual(self.watchlists.list_items(self.pool['id'])[0]['symbol'], 'OLD.SHF')
            self.repo.upsert_contracts(pd.DataFrame([
                dict(symbol=f'TEST_{index:03}.SHF', name=f'主力 {index}', exchange='SHFE', code=f'TEST_{index:03}',
                     main_symbol=f'TEST_{index:03}2701.SHF', main_name=f'品种{index}2701')
                for index in range(120)
            ]))
            self.repo.upsert_contracts(pd.DataFrame([
                dict(symbol='UNMAPPED.SHF', name='无映射主力', exchange='SHFE', code='UNMAPPED'),
            ]))
            self.assertEqual(service.search('UNMAPPED', 'FUTURES'), [])
            with self.assertRaises(WatchlistError):
                service.add_item(self.pool['id'], 'FUTURES', 'UNMAPPED.SHF')
            for _ in range(2):
                response = client.post('/watchlists/futures-pool/reset')
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), {'group_id': self.pool['id'], 'count': 120})
                items = self.watchlists.list_items(self.pool['id'])
                self.assertEqual([row['symbol'] for row in items], self.repo.list_contract_symbols())
                self.assertEqual([row['sort_order'] for row in items], list(range(120)))
                self.assertEqual(self.watchlists.list_items(custom['id']), [custom_item])
