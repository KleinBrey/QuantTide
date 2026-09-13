from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.app.database import DuckDBDatabase, HKDuckDBDatabase, USDuckDBDatabase
from backend.app.repository import (
    HKStockRepository,
    StockRepository,
    USStockRepository,
)
from backend.app.services import CNMarketService
from backend.scripts.init_hk_us_stock_pools import (
    HK_STOCKS,
    US_STOCKS,
    initialize_hk_us_stocks,
)


def _table_names(database: DuckDBDatabase) -> list[str]:
    with database.connection(read_only=True) as connection:
        return [
            row[0]
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                ORDER BY table_name
                """
            ).fetchall()
        ]


class MarketDatabaseSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        directory = Path(self.temp_dir.name)
        self.a_share_path = directory / "cn_market.duckdb"
        self.hk_path = directory / "hk_market.duckdb"
        self.us_path = directory / "us_market.duckdb"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_each_market_initializes_only_its_own_tables(self) -> None:
        a_share_database = DuckDBDatabase(self.a_share_path)
        hk_database = HKDuckDBDatabase(self.hk_path)
        us_database = USDuckDBDatabase(self.us_path)

        hk_database.initialize()
        HKStockRepository(hk_database).upsert_stocks(
            pd.DataFrame([{"symbol": "00700", "name": "旧格式腾讯"}])
        )
        for database in [a_share_database, hk_database, us_database]:
            database.initialize()

        self.assertEqual(
            _table_names(a_share_database),
            ["daily_bars", "stock_daily_basic", "stock_hot_daily", "stocks"],
        )
        self.assertEqual(
            _table_names(hk_database),
            ["daily_bars", "stock_hot_daily", "stocks"],
        )
        self.assertEqual(
            _table_names(us_database),
            ["daily_bars", "stock_hot_daily", "stocks"],
        )

        with a_share_database.connection(read_only=True) as connection:
            stock_columns = connection.execute("PRAGMA table_info('stocks')").df()[
                "name"
            ].tolist()
        self.assertEqual(
            stock_columns,
            ["symbol", "name", "exchange", "market", "source", "update_time"],
        )

        for database in [hk_database, us_database]:
            with database.connection(read_only=True) as connection:
                stock_columns = connection.execute(
                    "PRAGMA table_info('stocks')"
                ).df()["name"].tolist()
            self.assertEqual(
                stock_columns,
                ["symbol", "name", "source", "update_time"],
            )

    def test_stock_format_and_repository_do_not_require_type(self) -> None:
        database = DuckDBDatabase(self.a_share_path)
        database.initialize()
        formatted = CNMarketService.format_stock_list(
            pd.DataFrame(
                {
                    "ts_code": ["600519.SH"],
                    "name": ["贵州茅台"],
                    "exchange": ["SSE"],
                    "market": ["主板"],
                }
            ),
            "Tushare",
        )

        self.assertNotIn("type", formatted.columns)
        self.assertEqual(StockRepository(database).upsert_stocks(formatted), 1)
        self.assertNotIn("type", StockRepository(database).get_table_data().columns)

    def test_initial_hk_and_us_stock_pools_are_idempotent(self) -> None:
        hk_database = HKDuckDBDatabase(self.hk_path)
        us_database = USDuckDBDatabase(self.us_path)

        self.assertEqual(len(HK_STOCKS), 50)
        self.assertEqual(len(US_STOCKS), 50)
        self.assertEqual(len({symbol for symbol, _ in HK_STOCKS}), 50)
        self.assertEqual(len({symbol for symbol, _ in US_STOCKS}), 50)

        self.assertEqual(
            initialize_hk_us_stocks(hk_database, us_database),
            {"hk": 50, "us": 50},
        )
        self.assertEqual(
            initialize_hk_us_stocks(hk_database, us_database),
            {"hk": 50, "us": 50},
        )

        hk_stocks = HKStockRepository(hk_database).get_table_data()
        us_stocks = USStockRepository(us_database).get_table_data()
        self.assertEqual(len(hk_stocks), 50)
        self.assertEqual(len(us_stocks), 50)
        self.assertNotIn("00700", set(hk_stocks["symbol"]))
        self.assertEqual(
            hk_stocks.loc[hk_stocks["symbol"] == "00700.HK", "name"].item(),
            "腾讯控股",
        )
        self.assertEqual(
            us_stocks.loc[us_stocks["symbol"] == "NVDA", "name"].item(),
            "NVIDIA",
        )
        self.assertEqual(set(hk_stocks["source"]), {"Manual"})
        self.assertEqual(set(us_stocks["source"]), {"Manual"})

    def test_market_stock_repository_can_add_update_and_delete(self) -> None:
        database = HKDuckDBDatabase(self.hk_path)
        database.initialize()
        repository = HKStockRepository(database)

        self.assertEqual(
            repository.upsert_stocks(
                pd.DataFrame(
                    [
                        {"symbol": "00700", "name": "腾讯"},
                        {"symbol": " 00700 ", "name": "腾讯控股"},
                        {"symbol": "09988", "name": "阿里巴巴-W"},
                    ]
                )
            ),
            2,
        )
        stocks = repository.get_table_data()
        self.assertEqual(stocks["symbol"].tolist(), ["00700", "09988"])
        self.assertEqual(
            stocks.loc[stocks["symbol"] == "00700", "name"].item(),
            "腾讯控股",
        )

        self.assertEqual(repository.delete_stocks(["00700", "missing"]), 1)
        self.assertEqual(repository.get_table_data()["symbol"].tolist(), ["09988"])


if __name__ == "__main__":
    unittest.main()
