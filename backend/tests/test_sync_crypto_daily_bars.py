"""加密货币默认交易对池批量同步的集成回归。"""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from backend.app.database import CryptoDuckDBDatabase, SQLiteDatabase
from backend.app.repository.crypto_market_db import CryptoMarketRepository
from backend.app.repository.watchlist import WatchlistRepository
from backend.scripts.sync_crypto_daily_bars import sync_crypto_daily_bars


class SyncCryptoDailyBarsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.database = CryptoDuckDBDatabase(root / "crypto.duckdb")
        self.business = SQLiteDatabase(root / "app.sqlite")
        self.watchlists = WatchlistRepository(self.business)
        self.repository = CryptoMarketRepository(self.database)
        self.provider = Mock()
        self.row = {
            "date_ms": 1793404800000,  # 2026-10-31 00:00 UTC
            "open_price": 10, "high_price": 12, "low_price": 9,
            "close_price": 11, "volume": 2.5, "turnover": 27.5,
            "source": "Binance",
        }
        self.provider.fetch_historical.return_value = [self.row]

    def add_pool(self, symbols):
        self.business.initialize()
        pool = self.watchlists.ensure_default_pool("CRYPTO")
        for symbol in symbols:
            self.watchlists.add_item(pool["id"], "CRYPTO", symbol)

    def sync(self, **kwargs):
        return sync_crypto_daily_bars(
            provider=self.provider,
            database=self.database,
            app_database=self.business,
            request_interval=0,
            **kwargs,
        )

    def test_syncs_only_default_pool_with_shared_utc_range_and_upserts(self):
        self.add_pool(["BTCUSDT", "ETHUSDT"])
        custom = self.watchlists.create_group("其他交易对", "CRYPTO")
        self.watchlists.add_item(custom["id"], "CRYPTO", "DOGEUSDT")
        us_pool = self.watchlists.ensure_default_pool("US")
        self.watchlists.add_item(us_pool["id"], "US", "AAPL")
        now = datetime(2026, 10, 31, 10, 30, tzinfo=timezone.utc)
        with patch("backend.app.services.crypto_market_service.datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            self.assertEqual(self.sync(lookback_days=3, max_workers=2), {"symbols": 2, "rows": 2})

        calls = self.provider.fetch_historical.call_args_list
        self.assertEqual({call.args[0] for call in calls}, {"BTCUSDT", "ETHUSDT"})
        start = datetime(2026, 10, 29, tzinfo=timezone.utc)
        for call in calls:
            self.assertEqual(call.args[1:], (int(start.timestamp() * 1000), int(now.timestamp() * 1000)))
        bars = self.repository.get_daily_bars("BTCUSDT")
        self.assertEqual(len(bars), 1)
        self.assertEqual(str(bars[0]["trade_date"].date()), "2026-10-31")
        self.assertEqual(bars[0]["amount"], 27.5)
        self.assertEqual(bars[0]["source"], "Binance")

        self.row["close_price"] = 12
        self.sync(max_workers=1)
        bars = self.repository.get_daily_bars("BTCUSDT")
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["close"], 12)

    def test_initializes_databases_and_empty_pool_without_requesting_provider(self):
        # 注入行情数据库时，业务库默认使用同目录的 app.sqlite。
        result = sync_crypto_daily_bars(provider=self.provider, database=self.database)
        self.assertEqual(result, {"symbols": 0, "rows": 0})
        self.assertEqual(self.repository.list_symbols(), [])
        pool = self.watchlists.get_pool("CRYPTO")
        self.assertEqual(self.watchlists.list_items(pool["id"]), [])
        self.provider.fetch_historical.assert_not_called()

    def test_partial_failure_keeps_successful_data_and_attempts_remaining_symbols(self):
        self.add_pool(["BTCUSDT", "BADUSDT", "ETHUSDT"])

        def fetch(symbol, start, end):
            if symbol == "BADUSDT":
                raise requests.Timeout("request timed out")
            return [self.row]

        self.provider.fetch_historical.side_effect = fetch
        with self.assertRaisesRegex(RuntimeError, "已写入 2 条，失败交易对：BADUSDT"):
            self.sync(max_workers=1)
        self.assertEqual(self.provider.fetch_historical.call_count, 3)
        self.assertEqual(len(self.repository.get_daily_bars("BTCUSDT")), 1)
        self.assertEqual(len(self.repository.get_daily_bars("ETHUSDT")), 1)
        self.assertEqual(self.repository.get_daily_bars("BADUSDT"), [])

    def test_empty_response_is_skipped(self):
        self.add_pool(["BTCUSDT"])
        self.provider.fetch_historical.return_value = []
        self.assertEqual(self.sync(), {"symbols": 1, "rows": 0})
        self.assertEqual(self.repository.list_symbols(), [])

    def test_invalid_parameters_do_not_request_provider(self):
        for kwargs in [{"lookback_days": 0}, {"max_workers": 0}, {"request_interval": -1}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                sync_crypto_daily_bars(
                    provider=self.provider, database=self.database,
                    app_database=self.business, **kwargs,
                )
        self.provider.fetch_historical.assert_not_called()


if __name__ == "__main__":
    unittest.main()
