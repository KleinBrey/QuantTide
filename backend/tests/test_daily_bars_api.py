"""验证日 K 接口的市场参数、默认市场和对应仓库选择。"""

import unittest
from datetime import date
from unittest.mock import Mock

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import dependencies
from backend.app.api.daily_bars import router


class DailyBarsApiTests(unittest.TestCase):
    def setUp(self):
        def override_repository(repository):
            return lambda: repository

        app = FastAPI()
        app.include_router(router, prefix="/api")
        self.repositories = {}
        for index, (market, dependency) in enumerate([
            ("cn_stock", dependencies.get_daily_repository),
            ("hk_stock", dependencies.get_hk_daily_repository),
            ("us_stock", dependencies.get_us_daily_repository),
            ("futures", dependencies.get_futures_repository),
        ], start=1):
            repository = Mock()
            repository.get_by_symbol_and_date_range.return_value = pd.DataFrame([
                dict(symbol="TEST", trade_date="2026-10-30", open=index,
                     high=index, low=index, close=index, volume=100, source="Test"),
            ])
            self.repositories[market] = repository
            app.dependency_overrides[dependency] = override_repository(repository)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_market_selects_matching_repository_and_normalizes_symbol(self):
        for index, (market, raw, symbol) in enumerate([
            ("cn_stock", "600519.sh", "600519.SH"),
            ("hk_stock", "700", "00700.HK"),
            ("us_stock", "NVDA.O", "NVDA"),
            ("futures", "rb.shf", "RB.SHF"),
        ], start=1):
            with self.subTest(market=market):
                for repository in self.repositories.values():
                    repository.reset_mock()
                response = self.client.get("/api/daily-bars", params=dict(
                    market=market, symbol=raw, start="2026-10-01", end="2026-10-31",
                ))
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()[0]["close"], index)
                self.repositories[market].get_by_symbol_and_date_range.assert_called_once_with(
                    symbol, date(2026, 10, 1), date(2026, 10, 31),
                )
                for other_market, repository in self.repositories.items():
                    if other_market != market:
                        repository.get_by_symbol_and_date_range.assert_not_called()

    def test_omitted_market_uses_cn_stock(self):
        response = self.client.get("/api/daily-bars", params=dict(
            symbol="600519.SH", start="2026-10-01", end="2026-10-31",
        ))
        self.assertEqual(response.status_code, 200, response.text)
        self.repositories["cn_stock"].get_by_symbol_and_date_range.assert_called_once()
        for market in ("hk_stock", "us_stock", "futures"):
            self.repositories[market].get_by_symbol_and_date_range.assert_not_called()


if __name__ == "__main__":
    unittest.main()
