"""验证五类资产的当前分组同步范围、真实入库和错误处理，不请求外部行情。"""

import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.api import database_sync, routes
from backend.app.database import (
    CryptoDuckDBDatabase, DuckDBDatabase, FuturesDuckDBDatabase,
    HKDuckDBDatabase, SQLiteDatabase, USDuckDBDatabase,
)
from backend.app.provider import TushareProvider
from backend.app.repository import DailyBarRepository, HKDailyBarRepository, USDailyBarRepository
from backend.app.repository.crypto_market_db import CryptoMarketRepository
from backend.app.repository.futures_market_db import FuturesMarketRepository
from backend.app.repository.watchlist import WatchlistError, WatchlistRepository
from backend.app.services import CNMarketService, HKMarketService, USMarketService
from backend.app.services.crypto_market_service import CryptoMarketService
from backend.app.services.futures_market_service import FuturesMarketService


class WatchlistDailyBarSyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        business = SQLiteDatabase(root / "app.sqlite")
        business.initialize()
        self.watchlists = WatchlistRepository(business)
        self.group = self.watchlists.create_group("当前分组")
        self.other = self.watchlists.create_group("其他分组")
        self.repositories = {}
        symbols = {
            "CN": ("600519.SH", "000001.SZ"), "HK": ("00700.HK", "09988.HK"),
            "US": ("AAPL", "MSFT"), "CRYPTO": ("BTCUSDT", "ETHUSDT"),
            "FUTURES": ("RB.SHF", "AU.SHF"),
        }
        for market, database_class, repository_class in [
            ("CN", DuckDBDatabase, DailyBarRepository),
            ("HK", HKDuckDBDatabase, HKDailyBarRepository),
            ("US", USDuckDBDatabase, USDailyBarRepository),
            ("CRYPTO", CryptoDuckDBDatabase, CryptoMarketRepository),
            ("FUTURES", FuturesDuckDBDatabase, FuturesMarketRepository),
        ]:
            db = database_class(root / f"{market}.duckdb")
            db.initialize()
            self.repositories[market] = repository_class(db)
            self.watchlists.add_item(self.group["id"], market, symbols[market][0])
            self.watchlists.add_item(self.other["id"], market, symbols[market][1])
            if market != "CN":
                pool = self.watchlists.ensure_default_pool(market)
                self.watchlists.add_item(pool["id"], market, symbols[market][1])

        self.tushare = Mock()
        self.tushare.fetch_symbol_daily_bars.side_effect = lambda symbol, *_: pd.DataFrame([dict(
            ts_code=symbol, trade_date="20261030", open=10, high=12, low=9,
            close=11, vol=100, amount=20,
        )])
        self.tushare.fetch_futures_daily.side_effect = lambda symbol, *_: pd.DataFrame([dict(
            ts_code=symbol, trade_date="20261030", open=10, high=12, low=9,
            close=11, vol=100, amount=20, oi=30, settle=11,
        )])
        bar = dict(date_ms=1793318400000, open_price=10, high_price=12,
                   low_price=9, close_price=11, volume=100)
        self.yahoo = Mock()
        self.yahoo.fetch_historical.return_value = {"data": {"item": [bar]}}
        self.binance = Mock()
        self.binance.fetch_historical.return_value = [{**bar, "turnover": 20, "source": "Binance"}]
        self.app = FastAPI()
        self.app.state.watchlist_service = Mock(repository=self.watchlists)
        self.app.state.cn_market_service = CNMarketService(
            tushare_provider=self.tushare, daily_repository=self.repositories["CN"],
        )
        for market, cls in [("HK", HKMarketService), ("US", USMarketService)]:
            setattr(self.app.state, f"{market.lower()}_market_service", cls(
                yfinance_provider=self.yahoo, daily_repository=self.repositories[market],
                watchlist_repository=self.watchlists,
            ))
        self.app.state.crypto_market_service = CryptoMarketService(
            self.binance, self.repositories["CRYPTO"], watchlist_repository=self.watchlists,
        )
        self.app.state.futures_repository = self.repositories["FUTURES"]
        self.app.state.futures_market_service = FuturesMarketService(
            self.tushare, self.repositories["FUTURES"], self.watchlists,
        )
        self.app.include_router(routes.router, prefix="/api")

        @self.app.exception_handler(WatchlistError)
        async def watchlist_error_handler(request, error):
            return JSONResponse(status_code=error.status_code, content={"detail": str(error)})

        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        lock_patch = patch.object(database_sync, "database_sync_lock", threading.Lock())
        self.lock = lock_patch.start()
        self.addCleanup(lock_patch.stop)

    def sync(self, market, group_id=None):
        return self.client.post(
            f"/api/watchlists/groups/{group_id or self.group['id']}/sync-daily-bars",
            json={"market": market},
        )

    def saved_symbols(self, market):
        with self.repositories[market].db.connection(read_only=True) as connection:
            return connection.execute("SELECT symbol FROM daily_bars ORDER BY symbol").fetchall()

    def test_all_five_markets_update_only_current_group_and_current_market(self):
        expected = {"CN": "600519.SH", "HK": "00700.HK", "US": "AAPL",
                    "CRYPTO": "BTCUSDT", "FUTURES": "RB.SHF"}
        for market, symbol in expected.items():
            with self.subTest(market=market):
                response = self.sync(market)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), dict(
                    group_id=self.group["id"], market=market, symbols=1, rows=1,
                ))
                self.assertEqual(self.saved_symbols(market), [(symbol,)])
                self.assertFalse(self.lock.locked())
        self.tushare.fetch_daily_bar.assert_not_called()
        self.assertEqual(self.tushare.fetch_symbol_daily_bars.call_args.args[0], "600519.SH")
        self.assertEqual(self.tushare.fetch_futures_daily.call_args.args[0], "RB.SHF")
        self.assertEqual({call.args[0] for call in self.yahoo.fetch_historical.call_args_list}, {"00700.HK", "AAPL"})
        self.assertEqual(self.binance.fetch_historical.call_args.args[0], "BTCUSDT")
        # 重新获取会覆盖当前日行情，不生成重复记录。
        self.assertEqual(self.sync("CRYPTO").json()["rows"], 1)
        self.assertEqual(self.saved_symbols("CRYPTO"), [("BTCUSDT",)])

    def test_partial_failure_reports_error_keeps_success_and_releases_lock(self):
        self.watchlists.add_item(self.group["id"], "CRYPTO", "BADUSDT")
        self.watchlists.add_item(self.group["id"], "CRYPTO", "ETHUSDT")
        rows = self.binance.fetch_historical.return_value

        def fetch(symbol, *_):
            if symbol == "BADUSDT":
                raise RuntimeError("行情不可用")
            return rows

        self.binance.fetch_historical.side_effect = fetch
        response = self.sync("CRYPTO")
        self.assertEqual(response.status_code, 502)
        self.assertIn("已写入 2 条", response.json()["detail"])
        self.assertIn("BADUSDT", response.json()["detail"])
        self.assertEqual(self.saved_symbols("CRYPTO"), [("BTCUSDT",), ("ETHUSDT",)])
        self.assertFalse(self.lock.locked())
        self.binance.fetch_historical.side_effect = None
        self.assertEqual(self.sync("CRYPTO").status_code, 200)

    def test_busy_missing_empty_and_invalid_requests_do_not_fetch(self):
        with self.lock:
            self.assertEqual(self.sync("CN").status_code, 409)
        self.assertEqual(self.sync("CN", 99999).status_code, 404)
        empty = self.watchlists.create_group("空分组")
        self.assertEqual(self.sync("CN", empty["id"]).status_code, 422)
        self.assertEqual(self.sync("INVALID").status_code, 422)
        self.tushare.fetch_symbol_daily_bars.assert_not_called()
        self.assertFalse(self.lock.locked())

    def test_empty_upstream_response_returns_zero_rows(self):
        self.tushare.fetch_symbol_daily_bars.side_effect = None
        self.tushare.fetch_symbol_daily_bars.return_value = pd.DataFrame()
        self.tushare.fetch_futures_daily.side_effect = None
        self.tushare.fetch_futures_daily.return_value = pd.DataFrame()
        self.yahoo.fetch_historical.return_value = {"data": {"item": []}}
        self.binance.fetch_historical.return_value = []
        for market in self.repositories:
            with self.subTest(market=market):
                response = self.sync(market)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), dict(
                    group_id=self.group["id"], market=market, symbols=1, rows=0,
                ))
                self.assertEqual(self.saved_symbols(market), [])

    def test_empty_symbol_list_never_falls_back_to_default_pool(self):
        for market in self.repositories:
            with self.subTest(market=market):
                service = getattr(self.app.state, f"{market.lower()}_market_service")
                self.assertEqual(service.sync_group_daily_bars([]), {"symbols": 0, "rows": 0})
                self.assertEqual(self.saved_symbols(market), [])
        self.tushare.fetch_symbol_daily_bars.assert_not_called()
        self.tushare.fetch_futures_daily.assert_not_called()
        self.yahoo.fetch_historical.assert_not_called()
        self.binance.fetch_historical.assert_not_called()

    def test_cn_provider_passes_symbol_and_range_and_rejects_wrong_results(self):
        provider = TushareProvider.__new__(TushareProvider)
        provider.pro = Mock()
        rows = self.tushare.fetch_symbol_daily_bars("600519.SH")
        provider.pro.daily.return_value = rows
        start, end = date(2026, 10, 1), date(2026, 10, 31)
        pd.testing.assert_frame_equal(provider.fetch_symbol_daily_bars("600519.SH", start, end), rows)
        provider.pro.daily.assert_called_once_with(ts_code="600519.SH", start_date="20261001", end_date="20261031")
        for invalid in [rows.assign(ts_code="000001.SZ"), rows.assign(trade_date="20260930")]:
            provider.pro.daily.return_value = invalid
            with self.assertRaises(ValueError):
                provider.fetch_symbol_daily_bars("600519.SH", start, end)


if __name__ == "__main__":
    unittest.main()
