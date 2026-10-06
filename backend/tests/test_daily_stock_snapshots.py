"""股票池快照、历史数据同步与回测时点一致性回归。"""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd

from backend.app.database import DuckDBDatabase
from backend.app.provider import TushareProvider
from backend.app.repository import DailyStockRepository
from backend.quant.stock.universe import match_stock_snapshots
from backend.quant.signal.patterns.today_confirmed_breakout import TodayConfirmedBreakoutPattern


def snapshot(day, names):
    return pd.DataFrame([dict(symbol=symbol, trade_date=day, name=name,
                             exchange="SZ", market="主板", source="test")
                         for symbol, name in names.items()])


class DailyStockSnapshotsTests(unittest.TestCase):
    def test_snapshot_replacement_asof_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DuckDBDatabase(Path(tmp) / "cn.duckdb")
            db.initialize()
            repo = DailyStockRepository(db)
            repo.upsert_stocks(snapshot("2026-09-21", {"A": "旧名", "B": "退市"}))
            repo.upsert_stocks(snapshot("2026-09-23", {"A": "新名", "C": "新股"}))
            self.assertEqual(repo.get_as_of("2026-09-22").name.tolist(), ["旧名", "退市"])
            self.assertTrue(repo.get_as_of("2026-09-20").empty)
            self.assertEqual(repo.get_latest_data().symbol.tolist(), ["A", "C"])
            self.assertEqual(repo.get_symbols_in_range("2026-09-22", "2026-09-23"), ["A", "B", "C"])
            self.assertEqual(repo.get_symbols_in_range("2026-09-23", "2026-09-24"), ["A", "C"])
            repo.upsert_stocks(snapshot("2026-09-23", {"A": "ST新名"}))
            self.assertEqual(len(repo.get_table_data()), 3)
            self.assertEqual(repo.get_latest_data().symbol.tolist(), ["A"])
            for invalid in [snapshot("2026-09-23", {"A": None}), pd.DataFrame(),
                            snapshot("2026-09-23", {"A": "A"}).drop(columns="trade_date")]:
                with self.assertRaises(ValueError):
                    repo.upsert_stocks(invalid)
            self.assertEqual(repo.get_latest_data().name.tolist(), ["ST新名"])
            with db.connection(read_only=True) as c:
                self.assertEqual({r[0] for r in c.execute("show tables").fetchall()},
                                 {"daily_stocks", "daily_basic", "daily_hot", "daily_bars"})

    def test_whole_snapshot_does_not_resurrect_removed_members(self):
        history = pd.concat([snapshot("2020-01-02", {"A": "A", "B": "B"}),
                             snapshot("2020-01-06", {"B": "ST B"})])
        candidates = pd.DataFrame([dict(symbol=s, day=pd.Timestamp(day))
                                   for day in ["2020-01-01", "2020-01-03", "2020-01-07"]
                                   for s in ["A", "B"]])
        result = match_stock_snapshots(candidates, history, date_column="day")
        self.assertEqual(result.symbol.tolist(), ["A", "B", "B"])
        self.assertEqual(result.name.tolist(), ["A", "B", "ST B"])

    def test_bak_basic_uses_requested_day_and_rejects_wrong_or_truncated_data(self):
        provider = object.__new__(TushareProvider)
        provider.pro = Mock()
        raw = pd.DataFrame([dict(ts_code="000001.SZ", trade_date="20200102", name="旧名称", list_date="19910403"),
                            dict(ts_code="688001.SH", trade_date="20200102", name="科创", list_date="20190722"),
                            dict(ts_code="300001.SZ", trade_date="20200102", name="未上市", list_date="20200103")])
        provider.pro.bak_basic.return_value = raw
        result = provider.fetch_stock_list(date(2020, 1, 2))
        self.assertEqual(result.name.tolist(), ["旧名称", "科创"])
        self.assertEqual(result.market.tolist(), ["主板", "科创板"])
        self.assertEqual(provider.pro.bak_basic.call_args.kwargs["trade_date"], "20200102")
        provider.pro.stock_basic.assert_not_called()
        with self.assertRaises(ValueError):
            provider.fetch_stock_list(date(2020, 1, 3))
        provider.pro.bak_basic.return_value = pd.concat([raw.iloc[:1]] * 7000)
        with self.assertRaisesRegex(RuntimeError, "截断"):
            provider.fetch_stock_list(date(2020, 1, 2))

    def test_latest_stock_date_comes_from_calendar_not_today(self):
        provider = object.__new__(TushareProvider)
        provider.pro = Mock()
        provider.pro.trade_cal.return_value = pd.DataFrame([
            dict(cal_date="20260930", is_open=1),
            dict(cal_date="20261001", is_open=0),
        ])
        self.assertEqual(provider.fetch_trade_dates(date(2026, 9, 30), date(2026, 10, 5)), [date(2026, 9, 30)])

    def test_future_stock_names_membership_basic_heat_and_bars_do_not_change_past_signal(self):
        days = pd.bdate_range("2026-08-03", periods=26)
        prices = [*np.linspace(10.6, 10.0, 24), 10.3, 10.4]
        bars = pd.DataFrame([dict(symbol="A", trade_date=day, open=price - .1,
                                  high=price + .02, low=price - .11, close=price,
                                  volume=volume) for day, price, volume in zip(days, prices, [100]*24+[200, 150])])
        latest_stocks = snapshot(days[0], {"A": "历史名称"})
        basic = pd.DataFrame([dict(symbol="A", trade_date=days[0], market_cap=2e10)])
        heat = pd.DataFrame([dict(symbol="A", trade_date=days[-2], rank=5)])
        pattern = TodayConfirmedBreakoutPattern()
        baseline = pattern.scan(days[-1], latest_stocks, bars, heat, basic)
        self.assertEqual(baseline.name.tolist(), ["历史名称"])
        future = days[-1] + pd.Timedelta(days=10)
        actual = pattern.scan_range([days[-1]],
            pd.concat([latest_stocks, snapshot(future, {"A": "ST未来名称", "B": "未来新股"})]),
            pd.concat([bars, bars.tail(1).assign(trade_date=future, close=999, volume=999999)]),
            pd.concat([heat, heat.assign(trade_date=future, rank=1)]),
            pd.concat([basic, basic.assign(trade_date=future, market_cap=1)]))
        pd.testing.assert_frame_equal(baseline, actual)
        # 未来才出现的市值不能补给过去；单日和区间扫描执行同一限制。
        self.assertTrue(pattern.scan(days[-1], latest_stocks, bars, heat, basic.assign(trade_date=future)).empty)
        self.assertTrue(pattern.scan(days[-1], latest_stocks.assign(trade_date=future), bars, heat, basic).empty)
        no_past_heat = pattern.scan(days[-1], latest_stocks, bars, heat.assign(trade_date=future), basic)
        self.assertTrue(no_past_heat.hot_rank.isna().all())
        st_today = pd.concat([latest_stocks, snapshot(days[-1], {"A": "ST当日名称"})])
        self.assertTrue(pattern.scan(days[-1], st_today, bars, heat, basic).empty)


if __name__ == "__main__":
    unittest.main()
