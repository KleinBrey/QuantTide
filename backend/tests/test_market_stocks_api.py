from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes import router
from backend.app.database import HKDuckDBDatabase, USDuckDBDatabase
from backend.app.repository import HKStockRepository, USStockRepository


class MarketStocksApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        directory = Path(self.temp_dir.name)
        hk_database = HKDuckDBDatabase(directory / "hk_market.duckdb")
        us_database = USDuckDBDatabase(directory / "us_market.duckdb")
        hk_database.initialize()
        us_database.initialize()

        self.hk_repository = HKStockRepository(hk_database)
        self.us_repository = USStockRepository(us_database)
        self.hk_repository.upsert_stocks(
            pd.DataFrame(
                [
                    {"symbol": "09988.HK", "name": "阿里巴巴-W"},
                    {"symbol": "00700.HK", "name": "腾讯控股"},
                ]
            )
        )
        self.us_repository.upsert_stocks(
            pd.DataFrame([{"symbol": "NVDA", "name": "NVIDIA"}])
        )

        app = FastAPI()
        app.state.hk_stock_repository = self.hk_repository
        app.state.us_stock_repository = self.us_repository
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_market_stocks_reads_the_selected_database_stocks_table(self) -> None:
        hk_response = self.client.get(
            "/market-stocks", params={"market": "hk-share"}
        )
        us_response = self.client.get(
            "/market-stocks", params={"market": "us-share"}
        )

        self.assertEqual(hk_response.status_code, 200)
        self.assertEqual(
            [stock["symbol"] for stock in hk_response.json()],
            ["00700.HK", "09988.HK"],
        )
        self.assertEqual(us_response.status_code, 200)
        self.assertEqual(us_response.json()[0]["symbol"], "NVDA")

    def test_market_stocks_rejects_an_unsupported_market(self) -> None:
        response = self.client.get(
            "/market-stocks", params={"market": "a-share"}
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
