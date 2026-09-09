from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from backend.app.config.config import Settings
from backend.app.database import DuckDBDatabase
from backend.app.jobs.scheduler import create_scheduler
from backend.app.repository import StockDailyBasicRepository
from backend.app.services import Service


class FakeTushareProvider:
    def fetch_daily_basic(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": ["000001.SZ", "600000.SH"],
                "trade_date": [date(2026, 9, 8), date(2026, 9, 8)],
                "market_cap": [100_000_000_000.0, 200_000_000_000.0],
            }
        )


class StockDailyBasicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = DuckDBDatabase()
        self.database.database_path = Path(self.temp_dir.name) / "market.duckdb"
        self.database.initialize()
        self.repository = StockDailyBasicRepository(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_schema_contains_requested_columns(self) -> None:
        with self.database.connection(read_only=True) as connection:
            columns = connection.execute(
                "PRAGMA table_info('stock_daily_basic')"
            ).df()["name"].tolist()

        self.assertEqual(
            columns,
            ["symbol", "trade_date", "market_cap", "update_time"],
        )

    def test_upsert_returns_all_latest_snapshots(self) -> None:
        rows = pd.DataFrame(
            {
                "symbol": ["000001.SZ", "600000.SH"],
                "trade_date": [date(2026, 9, 8), date(2026, 9, 8)],
                "market_cap": [2.0, 3.0],
            }
        )

        affected_rows = self.repository.upsert_stock_daily_basic(rows)
        result = self.repository.get_table_data()

        self.assertEqual(affected_rows, 2)
        self.assertEqual(result["symbol"].tolist(), ["000001.SZ", "600000.SH"])
        self.assertEqual(result["market_cap"].tolist(), [2.0, 3.0])

    def test_new_trade_date_updates_matching_stock(self) -> None:
        self.repository.upsert_stock_daily_basic(
            pd.DataFrame(
                {
                    "symbol": ["000001.SZ", "600000.SH"],
                    "trade_date": [date(2026, 9, 8), date(2026, 9, 8)],
                    "market_cap": [1.0, 3.0],
                }
            )
        )
        self.repository.upsert_stock_daily_basic(
            pd.DataFrame(
                {
                    "symbol": ["000001.SZ"],
                    "trade_date": [date(2026, 9, 9)],
                    "market_cap": [2.0],
                }
            )
        )

        result = self.repository.get_table_data()

        self.assertEqual(len(result), 2)
        self.assertEqual(result.loc[0, "trade_date"].date(), date(2026, 9, 9))
        self.assertEqual(result.loc[0, "market_cap"], 2.0)

    def test_service_fetches_and_persists_latest_data(self) -> None:
        provider = FakeTushareProvider()
        service = Service(
            tushare_provider=provider,
            stock_daily_basic_repository=self.repository,
        )

        affected_rows = service.update_stock_daily_basic()
        result = self.repository.get_table_data()

        self.assertEqual(affected_rows, 2)
        self.assertEqual(len(result), 2)

    def test_scheduler_runs_weekday_sync_at_1600(self) -> None:
        scheduler = create_scheduler(Settings(scheduler_enabled=False))
        job = scheduler.get_job("weekday-stock-daily-basic-sync")

        self.assertIsNotNone(job)
        self.assertIn("hour='16'", str(job.trigger))
        self.assertIn("minute='0'", str(job.trigger))


if __name__ == "__main__":
    unittest.main()
