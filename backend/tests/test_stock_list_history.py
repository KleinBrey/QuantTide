"""历史股票池范围选择、并发拉取和默认覆盖回归。"""

import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from backend.app.database import DuckDBDatabase
from backend.app.repository import DailyStockRepository
from backend.scripts import sync_daily_stocks as script
from backend.app.services import cn_market_service as service_module
from backend.app.utils import concurrency
from backend.app.services import CNMarketService


class StockListHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = DuckDBDatabase(Path(temporary.name) / "stocks.duckdb")
        self.database.initialize()
        database_patch = patch.object(script, "DuckDBDatabase", return_value=self.database)
        database_patch.start()
        self.addCleanup(database_patch.stop)
        clock_patch = patch.object(service_module, "datetime")
        clock_patch.start().now.return_value = datetime(2026, 10, 6)
        self.addCleanup(clock_patch.stop)

    def test_cli_accepts_lookback_days(self):
        for days in [3, 60, 180, 365, 1095]:
            with self.subTest(days=days), patch.object(script, "sync_daily_stocks") as sync:
                script.main(['--lookback-days', str(days)])
                sync.assert_called_once_with(lookback_days=days)

    def test_natural_day_ranges_include_end_and_default_workers(self):
        end = date(2026, 10, 6)
        for days in [60, 180, 365, 1095]:
            with (
                self.subTest(days=days),
                patch.object(script, "TushareProvider") as provider,
                patch.object(concurrency, "ThreadPoolExecutor", wraps=concurrency.ThreadPoolExecutor) as executor,
            ):
                provider.return_value.fetch_trade_dates.return_value = [end]
                provider.return_value.fetch_stock_list.return_value = self.stock_rows(end)
                self.assertEqual(script.sync_daily_stocks(lookback_days=days), 1)
                provider.return_value.fetch_trade_dates.assert_called_once_with(end - timedelta(days=days - 1), end)
                executor.assert_called_once_with(max_workers=1, thread_name_prefix="daily-stocks")

    def test_parallel_fetch_overwrites_snapshots_and_preserves_failed_day(self):
        days = [date(2026, 9, 28), date(2026, 9, 29)]
        repository = DailyStockRepository(self.database)
        for day in days:
            old_rows = self.stock_rows(day).assign(name="旧名称")
            old_rows = pd.concat([old_rows, old_rows.assign(ts_code="000002.SZ")])
            repository.upsert_stocks(CNMarketService.format_stock_list(old_rows, "Tushare"))
        barrier = threading.Barrier(2, timeout=5)
        main_thread = threading.get_ident()
        fetch_threads = set()
        original_upsert = DailyStockRepository.upsert_stocks

        def fetch(day):
            fetch_threads.add(threading.get_ident())
            barrier.wait()
            if day == days[1]:
                raise RuntimeError("模拟接口失败")
            return self.stock_rows(day)

        def upsert(repository, rows):
            self.assertEqual(threading.get_ident(), main_thread)
            return original_upsert(repository, rows)

        with (
            patch.object(script, "TushareProvider") as provider,
            patch.object(DailyStockRepository, "upsert_stocks", autospec=True, side_effect=upsert),
        ):
            provider.return_value.fetch_trade_dates.return_value = days
            provider.return_value.fetch_stock_list.side_effect = fetch
            with self.assertRaisesRegex(RuntimeError, "2026-09-29"):
                script.sync_daily_stocks(60)
            self.assertEqual(len(fetch_threads), 2)
            self.assertNotIn(main_thread, fetch_threads)
            history = repository.get_table_data()
            self.assertEqual(len(history), 3)
            self.assertEqual(history.name.tolist().count("旧名称"), 2)
            self.assertEqual(history.name.tolist().count("平安银行"), 1)

            provider.return_value.fetch_stock_list = Mock(
                side_effect=lambda day: self.stock_rows(day).assign(name="新名称")
            )
            self.assertEqual(script.sync_daily_stocks(60), 2)
            self.assertEqual(provider.return_value.fetch_stock_list.call_count, 2)
            history = repository.get_table_data()
            self.assertEqual(history.name.tolist(), ["新名称", "新名称"])
            self.assertEqual(history.symbol.tolist(), ["000001.SZ", "000001.SZ"])

            provider.return_value.fetch_stock_list.reset_mock()
            self.assertEqual(script.sync_daily_stocks(60), 2)
            self.assertEqual(provider.return_value.fetch_stock_list.call_count, 2)
            self.assertEqual(len(DailyStockRepository(self.database).get_table_data()), 2)

    def test_rejects_invalid_arguments_before_fetching(self):
        provider = Mock()
        service = CNMarketService(tushare_provider=provider)
        for days in [0, -60]:
            with self.subTest(days=days), self.assertRaises(ValueError):
                service.update_daily_stocks(days)
        provider.fetch_trade_dates.assert_not_called()
        provider.fetch_stock_list.assert_not_called()

    def test_entry_defaults_to_three_natural_days(self):
        day = date(2026, 10, 5)
        with patch.object(script, "TushareProvider") as provider:
            provider.return_value.fetch_trade_dates.return_value = [day]
            provider.return_value.fetch_stock_list.return_value = self.stock_rows(day)
            script.sync_daily_stocks()
            provider.return_value.fetch_trade_dates.assert_called_once_with(
                date(2026, 10, 4), date(2026, 10, 6)
            )
            provider.return_value.fetch_stock_list.assert_called_once_with(day)
        rows = DailyStockRepository(self.database).get_table_data()
        self.assertEqual(rows.symbol.tolist(), ["000001.SZ"])
        self.assertEqual(rows.trade_date.dt.date.tolist(), [day])

    def test_service_without_days_saves_latest_snapshot(self):
        day = date(2026, 9, 30)
        provider = Mock()
        provider.fetch_stock_list.return_value = self.stock_rows(day)
        repository = DailyStockRepository(self.database)
        service = CNMarketService(tushare_provider=provider, daily_stock_repository=repository)
        self.assertEqual(service.update_daily_stocks(), 1)
        provider.fetch_stock_list.assert_called_once_with(None)
        provider.fetch_trade_dates.assert_not_called()
        self.assertEqual(repository.get_table_data().symbol.tolist(), ["000001.SZ"])

    def test_service_rejects_unsupported_range_and_skips_empty_calendar(self):
        provider, repository = Mock(), Mock()
        service = CNMarketService(
            tushare_provider=provider, daily_stock_repository=repository,
        )
        with self.assertRaisesRegex(ValueError, "2016-01-01"):
            service.update_daily_stocks(lookback_days=5000)
        provider.fetch_trade_dates.assert_not_called()
        provider.fetch_trade_dates.return_value = []
        with patch.object(concurrency, "ThreadPoolExecutor") as executor:
            self.assertEqual(service.update_daily_stocks(60), 0)
            executor.assert_not_called()
        provider.fetch_stock_list.assert_not_called()
        repository.upsert_stocks.assert_not_called()

    def test_latest_failure_preserves_existing_snapshot(self):
        day = date(2026, 9, 30)
        repository = DailyStockRepository(self.database)
        repository.upsert_stocks(
            CNMarketService.format_stock_list(self.stock_rows(day), "Tushare")
        )
        with patch.object(script, "TushareProvider") as provider:
            provider.return_value.fetch_stock_list.side_effect = RuntimeError("尚未发布")
            with self.assertRaisesRegex(RuntimeError, "股票池未完整同步.*最新交易日"):
                script.sync_daily_stocks(None)
        self.assertEqual(repository.get_table_data().name.tolist(), ["平安银行"])

    def test_empty_response_preserves_existing_snapshot(self):
        day = date(2026, 9, 30)
        repository = DailyStockRepository(self.database)
        repository.upsert_stocks(
            CNMarketService.format_stock_list(self.stock_rows(day), "Tushare")
        )
        existing = repository.get_table_data()
        for result in [None, pd.DataFrame()]:
            with self.subTest(result=result), patch.object(script, "TushareProvider") as provider:
                provider.return_value.fetch_stock_list.return_value = result
                self.assertEqual(script.sync_daily_stocks(None), 0)
            pd.testing.assert_frame_equal(repository.get_table_data(), existing)

    @staticmethod
    def stock_rows(day):
        return pd.DataFrame([dict(ts_code="000001.SZ", trade_date=day, name="平安银行",
                                  exchange="SZ", market="主板")])


if __name__ == "__main__":
    unittest.main()
