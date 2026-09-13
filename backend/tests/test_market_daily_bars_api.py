from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes import router
from backend.app.database import DuckDBDatabase, HKDuckDBDatabase, USDuckDBDatabase
from backend.app.repository import (
    DailyBarRepository,
    HKDailyBarRepository,
    USDailyBarRepository,
)
from backend.app.utils.symbol import normalize_daily_bar_symbol


def _daily_bar(symbol: str, close: float, source: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "trade_date": date(2026, 9, 11),
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 1_000,
                "amount": 100_000,
                "source": source,
            }
        ]
    )


class MarketDailyBarsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        directory = Path(self.temp_dir.name)
        databases = [
            DuckDBDatabase(directory / "cn_market.duckdb"),
            HKDuckDBDatabase(directory / "hk_market.duckdb"),
            USDuckDBDatabase(directory / "us_market.duckdb"),
        ]
        for database in databases:
            database.initialize()

        self.repositories = [
            DailyBarRepository(databases[0]),
            HKDailyBarRepository(databases[1]),
            USDailyBarRepository(databases[2]),
        ]
        self.repositories[0].upsert_daily_bars(
            _daily_bar("600519.SH", 101.0, "Tushare")
        )
        self.repositories[1].upsert_daily_bars(
            _daily_bar("00700.HK", 202.0, "Futu")
        )
        self.repositories[2].upsert_daily_bars(
            _daily_bar("NVDA", 303.0, "Futu")
        )

        app = FastAPI()
        app.state.daily_repository = self.repositories[0]
        app.state.hk_daily_repository = self.repositories[1]
        app.state.us_daily_repository = self.repositories[2]
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_daily_bars_route_reads_the_selected_market_database(self) -> None:
        cases = [
            ("a-share", "600519.SH", "600519.SH", 101.0),
            ("hk-share", "0700.HK", "00700.HK", 202.0),
            ("us-share", "NVDA.O", "NVDA", 303.0),
        ]

        for market, query_symbol, stored_symbol, expected_close in cases:
            with self.subTest(market=market):
                response = self.client.get(
                    "/daily-bars",
                    params={
                        "market": market,
                        "symbol": query_symbol,
                        "start": "2026-09-01",
                        "end": "2026-09-30",
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()), 1)
                self.assertEqual(response.json()[0]["symbol"], stored_symbol)
                self.assertEqual(response.json()[0]["close"], expected_close)

    def test_daily_bars_route_rejects_invalid_market(self) -> None:
        response = self.client.get(
            "/daily-bars",
            params={
                "market": "crypto",
                "symbol": "BTC",
                "start": "2026-09-01",
                "end": "2026-09-30",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_normalizes_hot_ranking_symbols_for_daily_bar_storage(self) -> None:
        self.assertEqual(
            normalize_daily_bar_symbol("HK.700", "hk-share"),
            "00700.HK",
        )
        self.assertEqual(
            normalize_daily_bar_symbol("0700.HK", "hk-share"),
            "00700.HK",
        )
        self.assertEqual(normalize_daily_bar_symbol("NVDA.O", "us-share"), "NVDA")
        self.assertEqual(normalize_daily_bar_symbol("BABA.N", "us-share"), "BABA")
        self.assertEqual(normalize_daily_bar_symbol("US.AAPL", "us-share"), "AAPL")


if __name__ == "__main__":
    unittest.main()
