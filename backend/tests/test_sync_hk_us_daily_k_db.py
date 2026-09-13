from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from backend.app.database import HKDuckDBDatabase, USDuckDBDatabase
from backend.app.repository import (
    HKDailyBarRepository,
    HKStockRepository,
    USDailyBarRepository,
    USStockRepository,
)
from backend.scripts.sync_hk_us_daily_k_db import (
    format_futu_daily_bars,
    sync_hk_us_daily_k,
)


class FakeFutuProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.session_count = 0

    @contextmanager
    def session(self):
        self.session_count += 1
        yield self

    def fetch_historical(self, symbol, start, end, interval, adjust):
        self.calls.append(
            {
                "symbol": symbol,
                "start": start,
                "end": end,
                "interval": interval,
                "adjust": adjust,
            }
        )
        return {
            "data": {
                "item": [
                    {
                        "date_ms": 1_788_192_000_000,
                        "open_price": 100.1,
                        "high_price": 102.2,
                        "low_price": 99.3,
                        "close_price": 101.4,
                        "volume": 1_000,
                        "turnover": 101_400.0,
                        "source": "Futu",
                    }
                ]
            }
        }


class SyncHKUSDailyKTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        directory = Path(self.temp_dir.name)
        self.hk_database = HKDuckDBDatabase(directory / "hk_market.duckdb")
        self.us_database = USDuckDBDatabase(directory / "us_market.duckdb")
        self.hk_database.initialize()
        self.us_database.initialize()
        HKStockRepository(self.hk_database).upsert_stocks(
            pd.DataFrame([{"symbol": "00700.HK", "name": "腾讯控股"}])
        )
        USStockRepository(self.us_database).upsert_stocks(
            pd.DataFrame([{"symbol": "AAPL", "name": "苹果"}])
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_formats_futu_history_for_daily_bars(self) -> None:
        rows = format_futu_daily_bars(
            "00700.HK",
            FakeFutuProvider().fetch_historical("00700.HK", 0, 1, "1d", "forward"),
        )

        self.assertEqual(rows.loc[0, "symbol"], "00700.HK")
        self.assertEqual(rows.loc[0, "trade_date"].isoformat(), "2026-09-01")
        self.assertEqual(rows.loc[0, "amount"], 101_400.0)
        self.assertEqual(rows.loc[0, "source"], "Futu")

    def test_syncs_each_stock_pool_into_its_own_database(self) -> None:
        provider = FakeFutuProvider()

        result = sync_hk_us_daily_k(
            lookback_days=60,
            max_workers=2,
            request_interval=0,
            provider=provider,
            hk_database=self.hk_database,
            us_database=self.us_database,
        )

        self.assertEqual(result["hk"], {"stocks": 1, "rows": 1, "failed_symbols": []})
        self.assertEqual(result["us"], {"stocks": 1, "rows": 1, "failed_symbols": []})
        self.assertEqual(
            {call["symbol"] for call in provider.calls},
            {"00700.HK", "AAPL"},
        )
        self.assertEqual(provider.session_count, 1)
        self.assertTrue(
            all(call["interval"] == "1d" for call in provider.calls)
        )
        self.assertTrue(
            all(call["adjust"] == "forward" for call in provider.calls)
        )

        hk_bars = HKDailyBarRepository(self.hk_database).get_table_data()
        us_bars = USDailyBarRepository(self.us_database).get_table_data()
        self.assertEqual(hk_bars["symbol"].tolist(), ["00700.HK"])
        self.assertEqual(us_bars["symbol"].tolist(), ["AAPL"])


if __name__ == "__main__":
    unittest.main()
