import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes import router
from backend.app.jobs.tasks import database_sync_lock
from backend.app.database import CryptoDuckDBDatabase, SQLiteDatabase
from backend.app.repository.crypto_market_db import CryptoMarketRepository
from backend.app.repository.watchlist import WatchlistRepository
from backend.app.services.crypto_market_service import CryptoMarketService
from backend.app.services.watchlist_service import WatchlistService


class CryptoMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = CryptoDuckDBDatabase(Path(self.tmp.name) / "crypto_market.duckdb")
        self.db.initialize()
        self.provider = Mock()
        self.repository = CryptoMarketRepository(self.db)
        app = FastAPI()
        app.state.crypto_market_service = CryptoMarketService(self.provider, self.repository)
        app.include_router(router, prefix="/api")
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_sync_persistence_utc_date_and_upsert(self):
        row = {"date_ms": 1767225600000, "open_price": 10, "high_price": 12,
               "low_price": 9, "close_price": 11, "volume": 2.5,
               "turnover": 27.5, "source": "Binance USD-M Perpetual"}
        self.provider.fetch_historical.return_value = [row]
        self.assertEqual(self.client.get("/api/crypto/symbols").json(), [])
        self.assertIsNone(self.repository.get_latest_update_time())
        response = self.client.post("/api/crypto/sync", json={"symbol": " btcusdt "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"symbol": "BTCUSDT", "rows": 1})
        args = self.provider.fetch_historical.call_args.args
        self.assertEqual(args[0], "BTCUSDT")
        self.assertEqual(args[1] % 86400000, 0)
        row["close_price"] = 12
        self.client.post("/api/crypto/sync", json={"symbol": "BTCUSDT"})
        bars = self.client.get("/api/crypto/daily-bars/btcusdt").json()
        self.assertEqual(len(bars), 1)
        self.assertTrue(bars[0]["trade_date"].startswith("2026-01-01"))
        self.assertEqual(bars[0]["close"], 12)
        self.assertEqual(bars[0]["amount"], 27.5)
        self.assertEqual(self.client.get("/api/crypto/symbols").json()[0]["symbol"], "BTCUSDT")
        self.assertIsNotNone(self.repository.get_latest_update_time())
        # 重建连接后仍可读取，证明页面使用的是落盘行情。
        self.db.initialize()
        self.assertEqual(len(self.repository.get_daily_bars("BTCUSDT")), 1)

    def test_shared_lock_prevents_sync_without_requesting_provider(self):
        with database_sync_lock:
            response = self.client.post("/api/crypto/sync", json={"symbol": "BTCUSDT"})
        self.assertEqual(response.status_code, 409)
        self.provider.fetch_historical.assert_not_called()

    def test_daily_bars_serves_perpetual_chart_and_watchlist_quotes(self):
        self.assertEqual(self.client.get('/api/crypto/symbols').json(), [])
        self.assertEqual(self.client.get('/api/crypto/daily-bars/BTCUSDT').json(), [])
        self.assertIsNone(self.repository.get_latest_update_time())

        business = SQLiteDatabase(Path(self.tmp.name) / 'app.sqlite')
        business.initialize()
        watchlists = WatchlistRepository(business)
        group = watchlists.ensure_default_pool('CRYPTO')
        watchlists.add_item(group['id'], 'CRYPTO', 'BTCUSDT')
        self.client.app.state.watchlist_service = WatchlistService(
            watchlists, Mock(), Mock(), Mock(), crypto_repository=self.repository,
        )
        items_url = f"/api/watchlists/groups/{group['id']}/items"
        self.assertIsNone(self.client.get(items_url).json()[0]['price'])

        self.provider.fetch_historical.return_value = [
            dict(date_ms=1767225600000 + day * 86400000, open_price=20,
                 high_price=22, low_price=19, close_price=close, volume=1,
                 turnover=close, source='Binance USD-M Perpetual')
            for day, close in [(0, 20), (1, 22)]
        ]
        response = self.client.post('/api/crypto/sync', json={'symbol': 'BTCUSDT'})
        self.assertEqual(response.json()['rows'], 2)
        bars = self.client.get('/api/crypto/daily-bars/BTCUSDT').json()
        self.assertEqual([bar['close'] for bar in bars], [20, 22])
        self.assertEqual({bar['source'] for bar in bars}, {'Binance USD-M Perpetual'})
        item = self.client.get(items_url).json()[0]
        self.assertEqual(item['price'], 22)
        self.assertAlmostEqual(item['change_pct'], 10)
        self.assertTrue(item['quote_date'].startswith('2026-01-02'))
        self.db.initialize()
        self.assertEqual([bar["close"] for bar in self.repository.get_daily_bars("BTCUSDT")], [20, 22])
        with self.db.connection() as connection:
            self.assertEqual(connection.execute("SHOW TABLES").fetchall(), [("daily_bars",)])

    def test_invalid_empty_and_upstream_failure(self):
        for body in [{"symbol": "BTC/USDT"}, {"symbol": "BTCUSDT", "days": 0}]:
            self.assertEqual(self.client.post("/api/crypto/sync", json=body).status_code, 422)
        self.provider.fetch_historical.assert_not_called()
        self.provider.fetch_historical.return_value = []
        self.assertEqual(self.client.post("/api/crypto/sync", json={"symbol": "BTCUSDT"}).json()["rows"], 0)
        self.provider.fetch_historical.side_effect = requests.Timeout()
        self.assertEqual(self.client.post("/api/crypto/sync", json={"symbol": "BTCUSDT"}).status_code, 502)
        self.assertEqual(self.client.get("/api/crypto/symbols").json(), [])
        # 请求失败后必须释放同步锁，下一次仍可执行。
        self.provider.fetch_historical.side_effect = None
        self.assertEqual(self.client.post("/api/crypto/sync", json={"symbol": "ETHUSDT"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
