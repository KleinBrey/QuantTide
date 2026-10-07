"""SQLite 业务边界、一次性迁移和跨市场自选 API 的集成回归。"""
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_watchlist_service
from backend.app.api.watchlists import router
from backend.app.database import SQLiteDatabase, DuckDBDatabase, HKDuckDBDatabase, USDuckDBDatabase
from backend.app.repository import DailyStockRepository, HKStockRepository, USStockRepository
from backend.app.repository.watchlist import WatchlistError, WatchlistRepository
from backend.app.services.watchlist_service import WatchlistService
from backend.scripts.latest.sync_hk_us_daily_bars import sync_hk_us_daily_bars


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.business = SQLiteDatabase(root / 'app.sqlite')
        self.business.initialize()
        self.repository = WatchlistRepository(self.business)
        self.databases = [DuckDBDatabase(root / 'cn.duckdb'), HKDuckDBDatabase(root / 'hk.duckdb'), USDuckDBDatabase(root / 'us.duckdb')]
        for db in self.databases:
            db.initialize()
        self.cn = DailyStockRepository(self.databases[0])
        self.hk = HKStockRepository(self.databases[1])
        self.us = USStockRepository(self.databases[2])
        self.cn.upsert_stocks(pd.DataFrame([dict(trade_date='2026-10-06', symbol='300308.SZ', name='中际旭创', exchange='SZ', market='创业板', source='Test')]))
        self.hk.upsert_stocks(pd.DataFrame([dict(symbol='00700.HK', name='腾讯控股', source='Test')]))
        self.us.upsert_stocks(pd.DataFrame([dict(symbol='NVDA', name='英伟达', source='Test'), dict(symbol='AAPL', name='苹果', source='Test')]))
        self.repository.migrate_stock_pools(['00700.HK'], ['NVDA', 'AAPL'])
        self.service = WatchlistService(self.repository, self.cn, self.hk, self.us)
        app = FastAPI()
        app.include_router(router, prefix='/api')
        app.dependency_overrides[get_watchlist_service] = lambda: self.service

        @app.exception_handler(WatchlistError)
        async def handler(request, error):
            return JSONResponse(status_code=error.status_code, content={'detail': str(error)})

        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def create_group(self, name='AI算力', market=None):
        response = self.client.post('/api/watchlists/groups', json={'name': name, 'market': market})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def add_item(self, group_id, market, symbol, status=201):
        response = self.client.post(f'/api/watchlists/groups/{group_id}/items', json={'market': market, 'symbol': symbol})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def test_migration_only_once_and_has_two_business_tables(self):
        groups = self.repository.list_groups()
        pools = [group for group in groups if group['is_default']]
        self.assertEqual([(group['market'], group['name'], group['item_count']) for group in pools], [('HK', 'stock_pool', 1), ('US', 'stock_pool', 2)])
        us_id = self.repository.get_pool('US')['id']
        self.repository.remove_stock(us_id, 'US', 'NVDA')
        fresh = WatchlistRepository(self.business)
        fresh.migrate_stock_pools(['00700.HK'], ['NVDA', 'AAPL', 'MSFT'])
        self.assertEqual([item['symbol'] for item in fresh.list_items(us_id)], ['AAPL'])
        with self.business.connection() as connection:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
            self.assertEqual(tables, ['watchlist_groups', 'watchlist_items'])
            self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        with self.assertRaises(WatchlistError):
            self.repository.get_pool('CN')

    def test_default_group_protected_at_api_and_database(self):
        for market in ['HK', 'US']:
            group_id = self.repository.get_pool(market)['id']
            self.assertEqual(self.client.delete(f'/api/watchlists/groups/{group_id}').status_code, 409)
            self.assertEqual(self.client.patch(f'/api/watchlists/groups/{group_id}', json={'name': '新名称'}).status_code, 409)
            for sql in ['DELETE FROM watchlist_groups WHERE id = ?', 'UPDATE watchlist_groups SET is_default = 0 WHERE id = ?']:
                with self.assertRaises(sqlite3.IntegrityError), self.business.connection() as connection:
                    connection.execute(sql, (group_id,))

    def test_cn_group_lifecycle_without_stock_pool(self):
        first = self.create_group('A股自选', 'CN')
        second = self.create_group('A股观察', 'CN')
        rows = self.client.get('/api/watchlists/stocks/search', params={'q': '中际', 'market': 'CN'}).json()
        self.assertEqual([row['symbol'] for row in rows], ['300308.SZ'])
        item = self.add_item(first, 'CN', '300308')
        self.add_item(first, 'CN', '300308.SZ', 409)
        self.add_item(first, 'US', 'NVDA', 422)
        self.add_item(second, 'CN', item['symbol'])
        self.assertEqual(self.client.patch(f'/api/watchlists/groups/{first}', json={'name': 'A股核心'}).status_code, 200)
        self.assertEqual(self.client.get(f'/api/watchlists/groups/{first}/items').json()[0]['name'], '中际旭创')
        self.assertEqual(self.client.delete(f'/api/watchlists/groups/{first}/items/{item["id"]}').status_code, 200)
        self.assertEqual(self.repository.list_items(first), [])
        self.assertEqual(len(self.repository.list_items(second)), 1)
        self.assertEqual(self.client.delete(f'/api/watchlists/groups/{second}').status_code, 200)
        self.assertEqual(self.service.search('300308', 'CN')[0]['name'], '中际旭创')
        self.assertFalse(any(group['market'] == 'CN' and group['is_default'] for group in self.repository.list_groups()))

    def test_cross_market_group_duplicate_normalization_and_metadata(self):
        first, second = self.create_group(), self.create_group('待观察')
        for market, raw, canonical in [('CN', '300308', '300308.SZ'), ('HK', '700', '00700.HK'), ('US', ' nvda.o ', 'NVDA')]:
            self.assertEqual(self.add_item(first, market, raw)['symbol'], canonical)
        self.add_item(first, 'HK', 'HK.00700', 409)
        self.add_item(first, 'US', 'NVDA', 409)
        self.add_item(second, 'US', 'NVDA')
        items = self.client.get(f'/api/watchlists/groups/{first}/items').json()
        self.assertEqual([item['name'] for item in items], ['中际旭创', '腾讯控股', '英伟达'])
        self.us.upsert_stocks(pd.DataFrame([dict(symbol='NVDA', name='新名称', source='Updated')]))
        self.assertEqual(self.service.list_items(first)[-1]['name'], '新名称')
        hk_pool = self.repository.get_pool('HK')['id']
        self.add_item(hk_pool, 'US', 'NVDA', 422)
        with self.assertRaises(sqlite3.IntegrityError), self.business.connection() as connection:
            connection.execute('INSERT INTO watchlist_items (group_id, market, symbol) VALUES (?, ?, ?)', (hk_pool, 'US', 'NVDA'))

    def test_validation_missing_group_stock_and_scoped_delete(self):
        group_id = self.create_group()
        for market, symbol, status in [('CN', '../600519', 422), ('HK', 'NVDA', 422), ('US', '  ', 422), ('US', '../NVDA', 422), ('US', 'NOTFOUND', 404), ('XX', 'NVDA', 422)]:
            self.add_item(group_id, market, symbol, status)
        self.add_item(999, 'US', 'NVDA', 404)
        for name in [' ', 'stock_pool', 'STOCK_POOL']:
            self.assertEqual(self.client.post('/api/watchlists/groups', json={'name': name}).status_code, 422)
        item = self.add_item(group_id, 'US', 'NVDA')
        self.assertEqual(self.client.delete(f'/api/watchlists/groups/1/items/{item["id"]}').status_code, 404)
        self.assertEqual(len(self.repository.list_items(group_id)), 1)

    def test_cascade_preserves_other_groups_and_market_data(self):
        group_id = self.create_group()
        self.add_item(group_id, 'US', 'NVDA')
        self.assertEqual(self.client.delete(f'/api/watchlists/groups/{group_id}').status_code, 200)
        with self.business.connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM watchlist_items WHERE group_id = ?', (group_id,)).fetchone()[0], 0)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO watchlist_items (group_id, market, symbol) VALUES (999, 'US', 'NVDA')")
        self.assertEqual(len(self.us.get_table_data()), 2)
        self.assertEqual(len(self.repository.list_items(self.repository.get_pool('US')['id'])), 2)

    def test_sorting_persists_and_invalid_order_is_atomic(self):
        group_id = self.create_group()
        first = self.add_item(group_id, 'US', 'NVDA')['id']
        second = self.add_item(group_id, 'US', 'AAPL')['id']
        path = f'/api/watchlists/groups/{group_id}/items/order'
        self.assertEqual(self.client.put(path, json={'ids': [second, first]}).status_code, 200)
        for invalid in [[first], [first, first], [first, 999]]:
            self.assertEqual(self.client.put(path, json={'ids': invalid}).status_code, 409)
        fresh = WatchlistRepository(self.business)
        self.assertEqual([row['id'] for row in fresh.list_items(group_id)], [second, first])
        ids = [group['id'] for group in self.repository.list_groups()][::-1]
        self.assertEqual(self.client.put('/api/watchlists/groups/order', json={'ids': ids}).status_code, 200)
        self.assertEqual([row['id'] for row in fresh.list_groups()], ids)
        self.assertEqual(self.client.put('/api/watchlists/groups/order', json={'ids': ids[:-1]}).status_code, 409)

    def test_concurrent_duplicate_has_one_winner(self):
        group_id = self.create_group()

        def add(_):
            try:
                self.repository.add_item(group_id, 'US', 'NVDA')
                return 201
            except WatchlistError as error:
                return error.status_code

        with ThreadPoolExecutor(max_workers=4) as executor:
            self.assertEqual(sorted(executor.map(add, range(4))), [201, 409, 409, 409])

    def test_search_routes_to_market_and_missing_metadata_retains_item(self):
        path = '/api/watchlists/stocks/search'
        for query, market, symbol in [('腾讯', 'HK', '00700.HK'), ('nvda', 'US', 'NVDA'), ('300308', 'CN', '300308.SZ')]:
            rows = self.client.get(path, params={'q': query, 'market': market}).json()
            self.assertEqual(rows[0]['symbol'], symbol)
            self.assertEqual(rows[0]['market'], market)
        self.assertEqual(self.client.get(path, params={'q': 'NVDA', 'market': 'HK'}).json(), [])
        self.assertEqual(self.client.get(path, params={'q': '  '}).status_code, 422)
        group_id = self.create_group()
        self.add_item(group_id, 'US', 'NVDA')
        self.us.delete_stocks('NVDA')
        self.assertEqual(self.service.list_items(group_id)[0]['name'], 'NVDA')

    def test_kline_sync_uses_sqlite_pool_after_removal(self):
        pool = self.repository.get_pool('US')['id']
        self.repository.remove_stock(pool, 'US', 'NVDA')
        provider = Mock()
        provider.fetch_historical.return_value = {'data': {'item': []}}
        results = sync_hk_us_daily_bars(3, 1, 0, provider=provider, hk_database=self.databases[1], us_database=self.databases[2], app_database=self.business)
        self.assertEqual(results['us']['stocks'], 1)
        self.assertEqual({call.args[0] for call in provider.fetch_historical.call_args_list}, {'00700.HK', 'AAPL'})
        self.assertEqual(len(self.us.get_table_data()), 2)

    def test_failed_migration_rolls_back_groups_and_version(self):
        db = SQLiteDatabase(self.business.database_path.parent / 'failed.sqlite')
        db.initialize()
        repository = WatchlistRepository(db)
        with self.assertRaises(sqlite3.IntegrityError):
            repository.migrate_stock_pools([''], ['NVDA'])
        self.assertEqual(repository.list_groups(), [])
        with db.connection() as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 0)
        repository.migrate_stock_pools(['00700.HK'], ['NVDA'])
        self.assertEqual(len(repository.list_groups()), 3)


if __name__ == '__main__':
    unittest.main()
