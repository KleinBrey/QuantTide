"""按交易日同步全市场日 K 的回归测试，不调用真实行情接口。"""

import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, call, patch

import pandas as pd

from backend.app.database import DuckDBDatabase, SQLiteDatabase
from backend.app.provider import TushareProvider
from backend.app.repository import DailyBarRepository
from backend.app.services.cn_market_service import CNMarketService
from backend.app.services import cn_market_service as service_module
from backend.scripts import sync_daily_bars as script
from backend.app.jobs.scheduler import create_scheduler, job_id
from backend.app.repository.task import TaskRepository
from backend.app.services.task_service import TaskService
from backend.app.config.config import Settings


def daily_rows(day, close=10):
    return pd.DataFrame([
        dict(ts_code=symbol, trade_date=day.strftime("%Y%m%d"), open=9,
             high=11, low=8, close=close, vol=volume, amount=1234)
        for symbol, volume in [("000001.SZ", 100), ("600001.SH", 200),
                               ("000002.SZ", 0)]
    ])


class DailyBarSyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = DuckDBDatabase(Path(temporary.name) / "bars.duckdb")
        database.initialize()
        self.repository = DailyBarRepository(database)
        self.provider = TushareProvider.__new__(TushareProvider)
        self.provider.pro = Mock()
        self.service = CNMarketService(
            tushare_provider=self.provider, daily_repository=self.repository,
        )
        self.today = date(2026, 10, 6)
        clock = patch.object(service_module, "datetime")
        clock.start().now.return_value = datetime(2026, 10, 6)
        self.addCleanup(clock.stop)

    def calendar(self, days):
        self.provider.pro.trade_cal.return_value = pd.DataFrame({
            "cal_date": [day.strftime("%Y%m%d") for day in days],
            "is_open": [1] * len(days),
        })

    def test_trade_dates_full_market_and_idempotent_upserts(self):
        days = [date(2026, 9, 28), date(2026, 9, 30)]
        self.calendar(days)
        self.provider.pro.daily.side_effect = lambda trade_date: daily_rows(
            datetime.strptime(trade_date, "%Y%m%d").date()
        )
        main_thread = threading.get_ident()
        original_upsert = self.repository.upsert_daily_bars

        def upsert(rows):
            self.assertEqual(threading.get_ident(), main_thread)
            return original_upsert(rows)

        with patch.object(self.repository, "upsert_daily_bars", side_effect=upsert):
            self.assertEqual(self.service.update_daily_bars(60), 4)
        self.provider.pro.trade_cal.assert_called_once_with(
            exchange="SSE", start_date="20260808", end_date="20261006",
            is_open="1", fields="cal_date,is_open",
        )
        self.provider.pro.daily.assert_has_calls(
            [call(trade_date="20260928"), call(trade_date="20260930")], any_order=True,
        )
        self.assertEqual(self.provider.pro.daily.call_count, 2)
        rows = self.repository.get_table_data()
        self.assertEqual(set(rows.symbol), {"000001.SZ", "600001.SH"})
        self.assertEqual(len(rows), 4)
        self.provider.pro.daily.side_effect = lambda trade_date: daily_rows(
            datetime.strptime(trade_date, "%Y%m%d").date(), close=11,
        )
        self.assertEqual(self.service.update_daily_bars(60), 4)
        rows = self.repository.get_table_data()
        self.assertEqual(len(rows), 4)
        self.assertTrue(rows.close.eq(11).all())

    def test_natural_day_windows_include_today(self):
        self.provider.fetch_trade_dates = Mock(return_value=[])
        for days in [1, 3, 60, 365]:
            with self.subTest(days=days):
                self.assertEqual(self.service.update_daily_bars(days), 0)
                self.provider.fetch_trade_dates.assert_called_with(
                    self.today - timedelta(days=days - 1), self.today,
                )
        self.provider.pro.daily.assert_not_called()

    def test_invalid_window_does_not_fetch(self):
        for days in [0, -1]:
            with self.subTest(days=days), self.assertRaises(ValueError):
                self.service.update_daily_bars(days)
        self.provider.pro.trade_cal.assert_not_called()

    def test_empty_date_skipped_and_only_failed_date_reported(self):
        days = [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)]
        self.calendar(days)

        def fetch(trade_date):
            if trade_date == "20260929":
                raise RuntimeError("模拟接口错误")
            if trade_date == "20260930":
                return None
            return daily_rows(days[0])

        self.provider.pro.daily.side_effect = fetch
        with self.assertRaisesRegex(RuntimeError, "失败日期：2026-09-29$"):
            self.service.update_daily_bars(60)
        rows = self.repository.get_table_data()
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows.trade_date.dt.date), {days[0]})

    def test_provider_rejects_truncation_and_wrong_date(self):
        day = date(2026, 9, 30)
        for result, error in [
            (pd.concat([daily_rows(day)] * 2000), RuntimeError),
            (daily_rows(date(2026, 9, 29)), ValueError),
        ]:
            with self.subTest(error=error):
                self.provider.pro.daily.return_value = result
                with self.assertRaises(error):
                    self.provider.fetch_daily_bar(day)
        for result in [None, pd.DataFrame()]:
            self.provider.pro.daily.return_value = result
            self.assertTrue(self.provider.fetch_daily_bar(day).empty)

    def test_missing_volume_is_a_write_failure_not_silently_filtered(self):
        self.calendar([self.today])
        result = daily_rows(self.today)
        result.loc[0, "vol"] = None
        self.provider.pro.daily.return_value = result
        with self.assertRaisesRegex(RuntimeError, "已写入 0 条，失败日期：2026-10-06$"):
            self.service.update_daily_bars(1)
        self.assertTrue(self.repository.get_table_data().empty)

    def test_provider_keeps_zero_volume_and_service_skips_it(self):
        self.calendar([self.today])
        valid = daily_rows(self.today)
        placeholder = valid.iloc[:1].assign(
            ts_code="002667.SZ", open=0, high=0, low=0, close=22.19, vol=0
        )
        raw = pd.concat([valid, placeholder])
        self.provider.pro.daily.return_value = raw
        pd.testing.assert_frame_equal(self.provider.fetch_daily_bar(self.today), raw)
        with patch.object(service_module, "progress_write") as message:
            self.assertEqual(self.service.update_daily_bars(1), 2)
        message.assert_any_call(f"{self.today} 日 K 跳过 2 条零成交量记录")
        saved = self.repository.get_table_data()
        self.assertNotIn("002667.SZ", saved.symbol.tolist())
        self.assertNotIn("000002.SZ", saved.symbol.tolist())

    def test_only_placeholders_is_empty_without_writing(self):
        self.calendar([self.today])
        self.provider.pro.daily.return_value = daily_rows(self.today).assign(
            open=0, high=0, low=0, vol=0
        )
        with patch.object(self.repository, "upsert_daily_bars") as write:
            self.assertEqual(self.service.update_daily_bars(1), 0)
        write.assert_not_called()

    def test_invalid_prices_with_volume_still_fail_database_constraint(self):
        self.calendar([self.today])
        self.provider.pro.daily.return_value = daily_rows(self.today).assign(high=0)
        with self.assertRaisesRegex(RuntimeError, "已写入 0 条，失败日期：2026-10-06$"):
            self.service.update_daily_bars(1)
        self.assertTrue(self.repository.get_table_data().empty)

    def test_cli_passes_lookback_days(self):
        for days in [3, 60, 180, 365, 1095]:
            with self.subTest(days=days), patch.object(script, "sync_daily_bars") as sync:
                script.main(['--lookback-days', str(days)])
                sync.assert_called_once_with(lookback_days=days)

    def test_scheduler_and_job_use_date_based_signature(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = SQLiteDatabase(Path(temporary) / 'app.sqlite')
            database.initialize()
            repository = TaskRepository(database)
            for days, cron in [(3, '0 16 * * mon-fri'), (60, '0 16 * * sat'), (365, '0 16 1 * *')]:
                repository.create_task(dict(
                    name=f'日 K 同步 {days} 日', script_id='daily_bars', params={'lookback_days': days},
                    schedule={'trigger': 'cron', 'cron': cron}, enabled=True,
                ))
            settings = Settings(scheduler_enabled=False)
            scheduler = create_scheduler(settings)
            service = TaskService(repository=repository, scheduler=scheduler, settings=settings)
            service.load_scheduled_tasks()
            jobs = [task for task in service.repository.list_tasks() if task['script_id'] == 'daily_bars']
            self.assertEqual([task['params']['lookback_days'] for task in jobs], [3, 60, 365])
            for task in jobs:
                with self.subTest(task=task), patch('backend.scripts.sync_daily_bars.sync_daily_bars') as sync:
                    job = scheduler.get_job(job_id(task['id']))
                    self.assertEqual(job.args, (task['id'],))
                    job.func(*job.args)
                    sync.assert_called_once_with(lookback_days=task['params']['lookback_days'])


if __name__ == "__main__":
    unittest.main()
