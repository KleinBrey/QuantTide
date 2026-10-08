"""使用临时数据库验证港美股列表增删，避免影响用户股票池。"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_hk_stock_repository, get_us_stock_repository, get_watchlist_service
from backend.app.api.routes import router
from backend.app.database import HKDuckDBDatabase, USDuckDBDatabase, SQLiteDatabase
from backend.app.repository.watchlist import WatchlistRepository
from backend.app.services.watchlist_service import WatchlistService
from backend.app.repository import (
    HKDailyBarRepository, HKStockRepository, USDailyBarRepository, USStockRepository,
)


class MarketStockManagementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repositories = {}
        self.bars = {}
        app = FastAPI()
        app.include_router(router, prefix="/api")
        for market, db_class, stock_class, bar_class, dependency in [
            ("hk-share", HKDuckDBDatabase, HKStockRepository, HKDailyBarRepository, get_hk_stock_repository),
            ("us-share", USDuckDBDatabase, USStockRepository, USDailyBarRepository, get_us_stock_repository),
        ]:
            db = db_class(Path(temporary.name) / f"{market}.duckdb")
            db.initialize()
            repository = stock_class(db)
            self.repositories[market] = repository
            self.bars[market] = bar_class(db)
            app.dependency_overrides[dependency] = lambda repository=repository: repository
        sqlite = SQLiteDatabase(Path(temporary.name) / 'app.sqlite')
        sqlite.initialize()
        self.watchlists = WatchlistRepository(sqlite)
        self.watchlists.ensure_default_pool('HK')
        self.watchlists.ensure_default_pool('US')
        service = WatchlistService(self.watchlists, None, self.repositories['hk-share'], self.repositories['us-share'])
        app.dependency_overrides[get_watchlist_service] = lambda: service
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_add_normalizes_symbols_and_rejects_duplicate_without_overwriting(self):
        for market, raw, normalized in [
            ("hk-share", "700", "00700.HK"), ("us-share", " aapl ", "AAPL"),
        ]:
            with self.subTest(market=market):
                payload = {"market": market, "symbol": raw, "name": " 公司名称 "}
                response = self.client.post("/api/market-stocks", json=payload)
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(response.json()["symbol"], normalized)
                self.assertEqual(response.json()["name"], "公司名称")
                self.assertEqual(response.json()["source"], "Manual")
                duplicate = self.client.post("/api/market-stocks", json={**payload, "name": "新名称"})
                self.assertEqual(duplicate.status_code, 409)
                rows = self.client.get("/api/market-stocks", params={"market": market}).json()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["name"], "公司名称")

    def test_validation_does_not_write_invalid_records(self):
        for market, symbol, name in [
            ("hk-share", "AAPL", "公司"), ("hk-share", "123456", "公司"),
            ("us-share", "../AAPL", "公司"), ("us-share", " ", "公司"),
            ("hk-share", "700", "  "), ("a-share", "600519.SH", "公司"),
        ]:
            with self.subTest(market=market, symbol=symbol, name=name):
                response = self.client.post("/api/market-stocks", json={
                    "market": market, "symbol": symbol, "name": name,
                })
                self.assertEqual(response.status_code, 422, response.text)
        for repository in self.repositories.values():
            self.assertTrue(repository.get_table_data().empty)

    def test_hot_ranking_symbols_join_only_the_matching_sqlite_pool(self):
        for market, raw, symbol, market_code in [
            ('hk-share', '0700.HK', '00700.HK', 'HK'),
            ('us-share', 'NVDA.O', 'NVDA', 'US'),
        ]:
            with self.subTest(market=market):
                repository = self.repositories[market]
                repository.upsert_stocks(pd.DataFrame([{
                    'symbol': symbol, 'name': '原始名称', 'source': 'Test',
                }]))
                other_group = self.watchlists.create_group('观察组', market_code)
                self.watchlists.add_item(other_group['id'], market_code, symbol)
                # 有基础信息、属于其他分组均不能作为 stock_pool 高亮依据。
                self.assertEqual(self.client.get('/api/market-stocks', params={'market': market}).json(), [])
                payload = {'market': market, 'symbol': raw, 'name': '热榜名称'}
                response = self.client.post('/api/market-stocks', json=payload)
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(response.json()['symbol'], symbol)
                self.assertEqual(response.json()['name'], '原始名称')
                self.assertEqual(response.json()['source'], 'Test')
                fresh = WatchlistRepository(self.watchlists.db)
                pool = fresh.get_pool(market_code)
                self.assertEqual([item['symbol'] for item in fresh.list_items(pool['id'])], [symbol])
                self.assertEqual([item['symbol'] for item in self.client.get(
                    '/api/market-stocks', params={'market': market}).json()], [symbol])
                self.assertEqual(self.client.post('/api/market-stocks', json=payload).status_code, 409)
                self.assertEqual(len(fresh.list_items(pool['id'])), 1)
                self.assertEqual(len(fresh.list_items(other_group['id'])), 1)

    def test_delete_is_market_scoped_and_preserves_historical_bars(self):
        for market, symbol in [("hk-share", "00700.HK"), ("us-share", "AAPL")]:
            self.repositories[market].upsert_stocks(pd.DataFrame([{
                "symbol": symbol, "name": "公司", "source": "Manual",
            }]))
            market_code = 'HK' if market == 'hk-share' else 'US'
            self.watchlists.add_item(self.watchlists.get_pool(market_code)['id'], market_code, symbol)
            self.bars[market].upsert_daily_bars(pd.DataFrame([{
                "symbol": symbol, "trade_date": "2026-10-06", "open": 10,
                "high": 12, "low": 9, "close": 11, "volume": 100, "source": "Test",
            }]))
        for market, symbol in [("hk-share", "700"), ("us-share", "aapl")]:
            with self.subTest(market=market):
                for _ in range(2):
                    response = self.client.delete("/api/market-stocks", params={"market": market, "symbol": symbol})
                    self.assertEqual(response.status_code, 200)
                rows = self.client.get('/api/market-stocks', params={'market': market}).json()
                self.assertEqual(rows, [])
                self.assertEqual(len(self.repositories[market].get_table_data()), 1)
                self.assertEqual(len(self.bars[market].get_table_data()), 1)
                if market == "hk-share":
                    self.assertEqual(len(self.client.get('/api/market-stocks', params={'market': 'us-share'}).json()), 1)


if __name__ == "__main__":
    unittest.main()
