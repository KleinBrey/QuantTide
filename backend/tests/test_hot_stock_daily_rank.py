import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import duckdb

from backend.app.database import DuckDBDatabase
from backend.app.provider.hithink_provider import HithinkProvider
from backend.app.repository import DailyHotRepository, DailyStockRepository
from backend.app.services import CNMarketService
from backend.scripts.sync_daily_hot import sync_daily_hot


class HotStockDailyRankTests(unittest.TestCase):
    def test_service_preserves_historical_names_membership_and_write_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = DuckDBDatabase(Path(tmp) / "market.duckdb")
            database.initialize()
            stock_repository = DailyStockRepository(database)
            for day, members in [
                ("2026-09-21", {"A": "旧名称", "B": "已退池"}),
                ("2026-09-23", {"A": "新名称", "C": "新入池"}),
            ]:
                stock_repository.upsert_stocks(pd.DataFrame([
                    dict(symbol=symbol, trade_date=day, name=name,
                         exchange="SZ", market="cn_stock", source="test")
                    for symbol, name in members.items()
                ]))

            caller_thread = get_ident()
            fetch_threads, write_threads = [], []
            provider = Mock(spec=HithinkProvider)

            def fetch(symbol, start, end):
                fetch_threads.append(get_ident())
                return [
                    dict(date=f"2026-09-{day}", rank={"A": 1, "B": 2, "C": 3}[symbol],
                         name="接口当前名称", price=100, change_pct=5)
                    for day in [25, 24, 23, 22, 21]
                ]

            provider.fetch_hot_stock_rank_trend.side_effect = fetch
            hot_repository = DailyHotRepository(database)
            save_rows = hot_repository.fill_stock_hot_daily

            def save(rows):
                write_threads.append(get_ident())
                return save_rows(rows)

            service = CNMarketService(
                hithink_provider=provider,
                daily_stock_repository=stock_repository,
                daily_hot_repository=hot_repository,
            )
            with (
                patch("backend.app.services.cn_market_service.datetime") as clock,
                patch("backend.app.services.cn_market_service.time.sleep"),
                patch.object(hot_repository, "fill_stock_hot_daily", side_effect=save),
            ):
                clock.now.return_value = datetime(2026, 9, 24)
                self.assertEqual(service.update_daily_hot_history(3, max_workers=2), 6)

            rows = hot_repository.get_table_data().sort_values(["symbol", "trade_date"])
            self.assertEqual(
                list(zip(rows.symbol, rows.trade_date.dt.strftime("%Y-%m-%d"), rows.name)),
                [("A", "2026-09-22", "旧名称"),
                 ("A", "2026-09-23", "新名称"),
                 ("A", "2026-09-24", "新名称"),
                 ("B", "2026-09-22", "已退池"),
                 ("C", "2026-09-23", "新入池"),
                 ("C", "2026-09-24", "新入池")],
            )
            self.assertTrue(rows[["price", "change_pct"]].isna().all().all())
            self.assertTrue(rows.source.eq("Hithink").all())
            self.assertCountEqual(
                [call.args for call in provider.fetch_hot_stock_rank_trend.call_args_list],
                [(symbol, "2026-09-22", "2026-09-24") for symbol in ["A", "B", "C"]],
            )
            self.assertEqual(len(fetch_threads), 3)
            self.assertTrue(all(thread != caller_thread for thread in fetch_threads))
            self.assertEqual(write_threads, [caller_thread] * 3)

    def test_provider_checks_business_errors_and_passes_dates(self):
        response = Mock()
        response.json.return_value = {"code": 0, "data": {"item": [{"rank": 1740}]}}
        with patch("backend.app.provider.hithink_provider.requests.get", return_value=response) as get:
            provider = HithinkProvider()
            self.assertEqual(provider.fetch_hot_stock_rank_trend(
                "300034.SZ", "2026-06-21", "2026-06-23"
            ), [{"rank": 1740}])
            self.assertEqual(get.call_args.kwargs["params"], {
                "thscode": "300034.SZ", "start_date": "2026-06-21", "end_date": "2026-06-23"
            })
            response.json.return_value = {"code": 2001, "message": "invalid key"}
            with self.assertRaisesRegex(RuntimeError, "2001"):
                provider.fetch_hot_stock_rank_trend("300034.SZ", "2026-06-21", "2026-06-23")

    def test_sync_overwrites_conflicts_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = DuckDBDatabase(Path(tmp) / "market.duckdb")
            database.initialize()
            DailyStockRepository(database).upsert_stocks(pd.DataFrame([
                dict(symbol=symbol, trade_date="2025-10-01", name=symbol, exchange="SZ", market="cn_stock", source="test")
                for symbol in ["300034.SZ", "000001.SZ", "000002.SZ"]
            ]))
            settings = SimpleNamespace(database_path=database.database_path, sync_workers=2)

            def fetch(symbol, start, end):
                if symbol == "000002.SZ":
                    raise RuntimeError("请求失败")
                return [dict(thscode=symbol, date=start, rank=1740 if symbol == "300034.SZ" else 2147)]

            with (
                patch("backend.scripts.sync_daily_hot.get_settings", return_value=settings),
                patch("backend.app.services.cn_market_service.time.sleep"),
                patch.object(HithinkProvider, "fetch_hot_stock_rank_trend", side_effect=fetch),
            ):
                for _ in range(2):
                    with self.assertRaisesRegex(RuntimeError, "同步未完全完成"):
                        sync_daily_hot()
                repo = DailyHotRepository(database)
                history = repo.get_table_data()
                self.assertEqual(len(history), 2)
                self.assertEqual(history["rank"].tolist(), [1740, 2147])
                self.assertTrue(history["price"].isna().all())
                self.assertEqual(history["source"].tolist(), ["Hithink", "Hithink"])

                snapshot = history.copy()
                snapshot["source"] = "Iwencai"
                snapshot["price"] = 42.0
                repo.upsert_stock_hot_daily(snapshot)
                self.assertEqual(repo.fill_stock_hot_daily(history), 2)
                self.assertTrue(repo.get_table_data()["price"].isna().all())
                self.assertEqual(repo.get_table_data()["source"].tolist(), ["Hithink", "Hithink"])

                # 新股票占用已有排名时，替换旧股票，保留其他排名。
                conflict = history.iloc[:1].copy()
                conflict["symbol"] = "000002.SZ"
                self.assertEqual(repo.fill_stock_hot_daily(conflict), 1)
                self.assertEqual(repo.get_table_data()["symbol"].tolist(), ["000002.SZ", "000001.SZ"])
                self.assertEqual(len(repo.get_table_data()), 2)

                # 同股票换排名时，同时清理股票主键和排名唯一键的冲突。
                conflict["rank"] = 2147
                self.assertEqual(repo.fill_stock_hot_daily(conflict), 1)
                before = repo.get_table_data()
                self.assertEqual(before["symbol"].tolist(), ["000002.SZ"])
                self.assertEqual(before["rank"].tolist(), [2147])

                # 插入失败时，删除的旧记录必须恢复。
                conflict["name"] = None
                with self.assertRaises(duckdb.ConstraintException):
                    repo.fill_stock_hot_daily(conflict)
                pd.testing.assert_frame_equal(repo.get_table_data(), before)


if __name__ == "__main__":
    unittest.main()
