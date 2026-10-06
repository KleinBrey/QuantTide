"""历史股票池范围选择、并发拉取和默认覆盖回归。"""

import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from backend.app.database import DuckDBDatabase
from backend.app.repository import DailyStockRepository
from backend.scripts.history import sync_stock_list as script


class StockListHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = DuckDBDatabase(Path(temporary.name) / "stocks.duckdb")
        self.database.initialize()
        settings = SimpleNamespace(database_path=self.database.database_path, sync_workers=2)
        settings_patch = patch.object(script, "get_settings", return_value=settings)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        clock_patch = patch.object(script, "datetime")
        clock_patch.start().now.return_value = datetime(2026, 10, 6)
        self.addCleanup(clock_patch.stop)

    def test_menu_and_noninteractive_options(self):
        for choice, days in [("1", 60), ("2", 180), ("3", 365), ("4", 1095)]:
            with (
                self.subTest(choice=choice),
                patch("sys.argv", ["sync_stock_list", "--workers", "3"]),
                patch("builtins.input", return_value=choice),
                patch.object(script, "sync_stock_list_history") as sync,
            ):
                script.main()
                sync.assert_called_once_with(lookback_days=days, workers=3)
        with (
            patch("sys.argv", ["sync_stock_list", "--lookback-days", "180"]),
            patch("builtins.input") as prompt,
            patch.object(script, "sync_stock_list_history") as sync,
        ):
            script.main()
            prompt.assert_not_called()
            sync.assert_called_once_with(lookback_days=180, workers=None)
        for choice in ["e", "invalid"]:
            with (
                patch("sys.argv", ["sync_stock_list"]),
                patch("builtins.input", return_value=choice),
                patch.object(script, "sync_stock_list_history") as sync,
            ):
                script.main()
                sync.assert_not_called()

    def test_natural_day_ranges_include_end_and_default_workers(self):
        end = date(2026, 10, 6)
        for days in [60, 180, 365, 1095]:
            with (
                self.subTest(days=days),
                patch.object(script, "TushareProvider") as provider,
                patch.object(script, "ThreadPoolExecutor", wraps=script.ThreadPoolExecutor) as executor,
            ):
                provider.return_value.fetch_trade_dates.return_value = [end]
                provider.return_value.fetch_stock_list.return_value = self.stock_rows(end)
                self.assertEqual(script.sync_stock_list_history(lookback_days=days), 1)
                provider.return_value.fetch_trade_dates.assert_called_once_with(end - timedelta(days=days - 1), end)
                executor.assert_called_once_with(max_workers=2)

    def test_parallel_fetch_overwrites_snapshots_and_preserves_failed_day(self):
        days = [date(2026, 9, 28), date(2026, 9, 29)]
        repository = DailyStockRepository(self.database)
        for day in days:
            old_rows = self.stock_rows(day).assign(name="旧名称")
            old_rows = pd.concat([old_rows, old_rows.assign(ts_code="000002.SZ")])
            repository.upsert_stocks(script.CNMarketService.format_stock_list(old_rows, "Tushare"))
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
            patch.object(script.time, "sleep"),
            patch.object(DailyStockRepository, "upsert_stocks", autospec=True, side_effect=upsert),
        ):
            provider.return_value.fetch_trade_dates.return_value = days
            provider.return_value.fetch_stock_list.side_effect = fetch
            with self.assertRaisesRegex(RuntimeError, "2026-09-29"):
                script.sync_stock_list_history(60, workers=2)
            self.assertEqual(len(fetch_threads), 2)
            self.assertNotIn(main_thread, fetch_threads)
            history = repository.get_table_data()
            self.assertEqual(len(history), 3)
            self.assertEqual(history.name.tolist().count("旧名称"), 2)
            self.assertEqual(history.name.tolist().count("平安银行"), 1)

            provider.return_value.fetch_stock_list = Mock(
                side_effect=lambda day: self.stock_rows(day).assign(name="新名称")
            )
            self.assertEqual(script.sync_stock_list_history(60, workers=1), 2)
            self.assertEqual(provider.return_value.fetch_stock_list.call_count, 2)
            history = repository.get_table_data()
            self.assertEqual(history.name.tolist(), ["新名称", "新名称"])
            self.assertEqual(history.symbol.tolist(), ["000001.SZ", "000001.SZ"])

            provider.return_value.fetch_stock_list.reset_mock()
            self.assertEqual(script.sync_stock_list_history(60, workers=1), 2)
            self.assertEqual(provider.return_value.fetch_stock_list.call_count, 2)
            self.assertEqual(len(DailyStockRepository(self.database).get_table_data()), 2)

    def test_rejects_invalid_arguments_before_fetching(self):
        for kwargs in [{"workers": 0}, {"workers": -1}, {"lookback_days": 0},
                       {"lookback_days": -60}]:
            with self.subTest(kwargs=kwargs), patch.object(script, "TushareProvider") as provider:
                with self.assertRaises(ValueError):
                    script.sync_stock_list_history(**kwargs)
                provider.assert_not_called()

    @staticmethod
    def stock_rows(day):
        return pd.DataFrame([dict(ts_code="000001.SZ", trade_date=day, name="平安银行",
                                  exchange="SZ", market="主板")])


if __name__ == "__main__":
    unittest.main()
