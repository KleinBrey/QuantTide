"""区间扫描通过 API 返回同一股票的全部历史确认日。"""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.signals import router
from backend.tests.test_breakout_pullback_n import pattern


class SignalHistoryTests(unittest.TestCase):
    def setUp(self):
        first = pattern().rename(columns={"date": "trade_date"})
        second = first.assign(trade_date=first["trade_date"] + pd.Timedelta(days=len(first)))
        bars = pd.concat([first, second], ignore_index=True)
        self.first_hit = first["trade_date"].max().date().isoformat()
        self.second_hit = second["trade_date"].max().date().isoformat()
        snapshot = first["trade_date"].min()
        future = second["trade_date"].max() + pd.Timedelta(days=1)
        stocks = pd.DataFrame([
            {"symbol": "TEST", "name": "历史名称", "exchange": "SH", "trade_date": snapshot},
            {"symbol": "TEST", "name": "未来名称", "exchange": "SH", "trade_date": future},
        ])
        basic = stocks[["symbol", "trade_date"]].assign(market_cap=[100, 200])
        hot = stocks[["symbol", "trade_date"]].assign(rank=[3, 7])

        app = FastAPI()
        app.include_router(router)
        for name, frame in (
            ("daily_repository", bars), ("daily_stock_repository", stocks),
            ("daily_basic_repository", basic), ("daily_hot_repository", hot),
        ):
            setattr(app.state, name, SimpleNamespace(get_table_data=lambda frame=frame: frame))
        self.app = app
        self.bars = bars
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.path = "/signals/strong-breakout-pullback"

    def test_inclusive_range_preserves_warmup_and_all_dates(self):
        response = self.client.get(self.path, params={
            "start_date": self.first_hit, "end_date": self.second_hit,
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["stock_count"], 1)
        self.assertEqual([item["signal_date"] for item in result["items"]], [self.second_hit, self.first_hit])
        self.assertEqual({item["name"] for item in result["items"]}, {"历史名称"})
        self.assertEqual({item["market_cap"] for item in result["items"]}, {100})

    def test_single_day_and_reversed_range(self):
        same_day = self.client.get(self.path, params={
            "start_date": self.first_hit, "end_date": self.first_hit,
        })
        self.assertEqual(same_day.json()["count"], 1)
        reversed_range = self.client.get(self.path, params={
            "start_date": self.second_hit, "end_date": self.first_hit,
        })
        self.assertEqual(reversed_range.status_code, 422)

    def test_today_uses_latest_market_day_and_not_prior_hits(self):
        # 下一交易日没有大阳线，不能把更早的命中带到当日页。
        latest = self.bars.iloc[[-1]].copy()
        latest["trade_date"] += pd.Timedelta(days=1)
        latest[["open", "high", "low", "close"]] = [14.8, 14.9, 14.7, 14.8]
        bars = pd.concat([self.bars, latest], ignore_index=True)
        self.app.state.daily_repository.get_table_data = lambda: bars
        response = self.client.get(self.path, params={"mode": "today"})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["mode"], "today")
        self.assertEqual(result["start_date"], latest["trade_date"].iloc[0].date().isoformat())
        self.assertEqual(result["start_date"], result["end_date"])
        self.assertEqual(result["count"], 0)

    def test_today_returns_only_latest_day(self):
        response = self.client.get(self.path, params={"mode": "today"})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["end_date"], self.second_hit)
        self.assertEqual([item["signal_date"] for item in result["items"]], [self.second_hit])

    def test_empty_today_and_invalid_mode(self):
        self.app.state.daily_repository.get_table_data = lambda: self.bars.iloc[:0]
        response = self.client.get(self.path, params={"mode": "today"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)
        self.assertEqual(self.client.get(self.path, params={"mode": "unknown"}).status_code, 422)

    def test_history_requires_both_dates_before_reading_data(self):
        read_bars = Mock()
        self.app.state.daily_repository.get_table_data = read_bars
        for dates in ({}, {"start_date": self.first_hit}, {"end_date": self.second_hit}):
            for mode in ({}, {"mode": "history"}):
                with self.subTest(dates=dates, mode=mode):
                    response = self.client.get(self.path, params={**mode, **dates})
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(response.json()["detail"], "历史扫描必须提供开始日期和结束日期")
        read_bars.assert_not_called()
