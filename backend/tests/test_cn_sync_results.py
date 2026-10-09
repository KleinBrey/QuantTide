"""三个 A 股同步方法共用的空数据、失败统计和继续执行约定。"""

import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch

import pandas as pd

from backend.app.services import cn_market_service as service_module
from backend.app.services.cn_market_service import CNMarketService


SYNC_CASES = [
    ("update_daily_stocks", "fetch_stock_list", "daily_stock_repository", "upsert_stocks"),
    ("update_daily_basic", "fetch_daily_basic", "daily_basic_repository", "upsert_stock_daily_basic"),
    ("update_daily_bars", "fetch_daily_bar", "daily_repository", "upsert_daily_bars"),
]


def rows(day):
    # 同时提供三个同步方法所需的字段；每个日期只有一条记录。
    return pd.DataFrame([dict(
        ts_code="000001.SZ", symbol="000001.SZ", trade_date=day,
        name="平安银行", exchange="SZ", market="主板", market_cap=100,
        open=10, high=11, low=9, close=10, vol=100, amount=1000,
    )])


class CNSyncResultsTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(service_module, "datetime")
        clock.start().now.return_value = datetime(2026, 10, 9)
        self.addCleanup(clock.stop)

    def service(self, case, dates):
        update_name, fetch_name, repository_name, write_name = case
        provider, repository = Mock(), Mock()
        provider.fetch_trade_dates.return_value = dates
        service = CNMarketService(
            tushare_provider=provider, **{repository_name: repository}
        )
        return (
            getattr(service, update_name),
            getattr(provider, fetch_name),
            getattr(repository, write_name),
        )

    def test_empty_results_skip_writing_and_finish_successfully(self):
        for case in SYNC_CASES:
            for result in [None, pd.DataFrame()]:
                with self.subTest(method=case[0], result=result):
                    update, fetch, write = self.service(case, [date(2026, 10, 9)])
                    fetch.return_value = result
                    with (
                        patch.object(service_module, "progress_write") as message,
                        patch("backend.app.utils.progress.SyncProgress.finish") as finish,
                    ):
                        self.assertEqual(update(1), 0)
                    write.assert_not_called()
                    finish.assert_called_once_with(written=0, empty=1, failed=0)
                    self.assertIn("暂无数据，本次跳过", message.call_args.args[0])

    def test_empty_and_successful_dates_finish_without_error(self):
        days = [date(2026, 10, 8), date(2026, 10, 9)]
        for case in SYNC_CASES:
            with self.subTest(method=case[0]):
                update, fetch, write = self.service(case, days)
                fetch.side_effect = lambda day: rows(day) if day == days[0] else None
                write.return_value = 1
                with patch("backend.app.utils.progress.SyncProgress.finish") as finish:
                    self.assertEqual(update(2), 1)
                write.assert_called_once()
                finish.assert_called_once_with(written=1, empty=1, failed=0)

    def test_fetch_and_write_failures_are_collected_before_raising(self):
        days = [date(2026, 10, day) for day in [6, 7, 8, 9]]
        for case in SYNC_CASES:
            with self.subTest(method=case[0]):
                update, fetch, write = self.service(case, days)

                def fetch_rows(day):
                    if day == days[0]:
                        raise RuntimeError("接口异常")
                    if day == days[2]:
                        return pd.DataFrame()
                    return rows(day)

                def save(frame):
                    if frame.iloc[0]["trade_date"] == days[1]:
                        raise RuntimeError("写入异常")
                    return len(frame)

                fetch.side_effect = fetch_rows
                write.side_effect = save
                with patch("backend.app.utils.progress.SyncProgress.finish") as finish:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "已写入 1 条，失败日期：2026-10-06, 2026-10-07$",
                    ):
                        update(4)
                self.assertEqual(fetch.call_count, 4)
                self.assertEqual(write.call_count, 2)
                finish.assert_called_once_with(written=1, empty=1, failed=2)

    def test_zero_volume_bars_are_skipped(self):
        day = date(2026, 10, 9)
        update, fetch, write = self.service(SYNC_CASES[2], [day])
        fetch.return_value = rows(day).assign(vol=0)
        write.return_value = 1
        with patch("backend.app.utils.progress.SyncProgress.finish") as finish:
            self.assertEqual(update(1), 0)
        write.assert_not_called()
        finish.assert_called_once_with(written=0, empty=1, failed=0)


if __name__ == "__main__":
    unittest.main()
