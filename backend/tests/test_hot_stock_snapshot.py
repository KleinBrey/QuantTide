import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import duckdb
import pandas as pd

from backend.app.database import DuckDBDatabase, HKDuckDBDatabase, USDuckDBDatabase
from backend.app.repository.cn_market_db import DailyHotRepository
from backend.app.repository.hk_market_db import HKStockHotDailyRepository
from backend.app.repository.us_market_db import USStockHotDailyRepository
from backend.app.services.hot_stock_service import HotStockService
from backend.app.provider.iwencai_provider import IwencaiProvider, IwencaiError


class HotStockSnapshotTests(unittest.TestCase):
    def test_replace_swap_shrink_and_rollback_in_all_markets(self):
        for database, repository in [
            (DuckDBDatabase, DailyHotRepository),
            (HKDuckDBDatabase, HKStockHotDailyRepository),
            (USDuckDBDatabase, USStockHotDailyRepository),
        ]:
            with self.subTest(market=database.__name__), tempfile.TemporaryDirectory() as tmp:
                db = database(Path(tmp) / 'market.duckdb')
                db.initialize()
                repo = repository(db)

                def rows(symbols, day='2026-09-30'):
                    return pd.DataFrame([
                        dict(trade_date=day, symbol=s, name=s, price=1, change_pct=0, rank=i + 1)
                        for i, s in enumerate(symbols)
                    ])

                repo.upsert_stock_hot_daily(rows(['H'], '2026-09-29'))
                repo.upsert_stock_hot_daily(rows(['A', 'B']))
                repo.upsert_stock_hot_daily(rows(['B', 'A']))
                self.assertEqual(repo.get_latest_data().symbol.tolist(), ['B', 'A'])
                repo.upsert_stock_hot_daily(rows(['B', 'C']))
                self.assertEqual(repo.get_latest_data().symbol.tolist(), ['B', 'C'])
                repo.upsert_stock_hot_daily(rows(['C']))
                self.assertEqual(repo.get_latest_data().symbol.tolist(), ['C'])
                self.assertEqual(repo.get_by_trade_date('2026-09-29').symbol.tolist(), ['H'])
                before = repo.get_latest_data()
                invalid = rows(['X', 'Y'])
                invalid['rank'] = 1
                with self.assertRaises(ValueError):
                    repo.upsert_stock_hot_daily(invalid)
                with self.assertRaises(duckdb.ConstraintException):
                    repo.upsert_stock_hot_daily(rows(['X', 'X']))
                invalid = rows(['X'])
                invalid['name'] = None  # 插入失败发生在删除之后，必须回滚。
                with self.assertRaises(duckdb.ConstraintException):
                    repo.upsert_stock_hot_daily(invalid)
                self.assertEqual(repo.upsert_stock_hot_daily(pd.DataFrame()), 0)
                pd.testing.assert_frame_equal(repo.get_latest_data(), before)
                with db.connection() as connection:
                    with self.assertRaises(duckdb.ConstraintException):
                        table = "daily_hot" if database is DuckDBDatabase else "stock_hot_daily"
                        connection.execute(f"""INSERT INTO {table}
                            (trade_date, symbol, name, rank)
                            VALUES ('2026-09-30', 'Z', 'Z', 1)""")

    def test_service_rejects_empty_or_filtered_snapshot(self):
        provider, repository = Mock(), Mock()
        service = HotStockService(iwencai_provider=provider,
            stock_hot_repository=repository, fetch_method_name='fetch_hot_rank', market_name='测试')
        for frame in [pd.DataFrame(), pd.DataFrame([
            dict(symbol='A', name=None, price=1, change_pct=0, rank=1)
        ])]:
            provider.fetch_hot_rank.return_value = frame
            with self.assertRaises(ValueError):
                service.update_hot_stock('2026-09-30')
        # 热度缺失由格式化和 Service 的记录数检查统一拦截。
        provider.fetch_hot_rank.return_value = IwencaiProvider.format_hot_rank([
            {'股票代码': 'A', '股票简称': 'A', '个股热度': '--'}
        ])
        with self.assertRaises(ValueError):
            service.update_hot_stock('2026-09-30')
        repository.upsert_stock_hot_daily.assert_not_called()

    def test_provider_rejects_incomplete_page(self):
        provider = object.__new__(IwencaiProvider)
        provider.api_keys = ['test']
        provider._request_page = Mock(return_value={'code_count': 3, 'datas': [{'symbol': 'A'}]})
        with self.assertRaises(IwencaiError):
            provider.query('热榜', page_size=50)


if __name__ == '__main__':
    unittest.main()
