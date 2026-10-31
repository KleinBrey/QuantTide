"""期货同步入口的参数校验、失败中止和交互行为。"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import call, patch

from backend.scripts import sync_futures_market as script


class SyncFuturesMarketTests(unittest.TestCase):
    def test_invalid_lookback_has_no_initialization_or_sync_side_effects(self):
        for sync in (script.sync_futures_daily_bars, script.sync_futures_market):
            for value in (0, -1, True, False, 1.5, "60", None):
                with self.subTest(entry=sync.__name__, value=value):
                    with patch.object(script, "create_service") as factory:
                        with self.assertRaisesRegex(ValueError, "lookback_days"):
                            sync(value)
                        factory.assert_not_called()

    def test_full_sync_reuses_service_and_refreshes_contracts_before_daily_bars(self):
        with patch.object(script, "create_service") as factory:
            service = factory.return_value
            service.update_daily_bars.return_value = {"contracts": 2, "rows": 120}
            self.assertEqual(script.sync_futures_market(60), {"contracts": 2, "rows": 120})
            factory.assert_called_once_with()
            self.assertEqual(service.mock_calls, [call.update_contracts(), call.update_daily_bars(60)])

    def test_failed_contract_refresh_does_not_start_daily_sync(self):
        with patch.object(script, "create_service") as factory:
            service = factory.return_value
            service.update_contracts.side_effect = RuntimeError("合约更新失败")
            with self.assertRaisesRegex(RuntimeError, "合约更新失败"):
                script.sync_futures_market()
            service.update_daily_bars.assert_not_called()

    def test_daily_failure_propagates_to_task_runner(self):
        with patch.object(script, "create_service") as factory:
            factory.return_value.update_daily_bars.side_effect = RuntimeError("部分批次失败")
            for sync in (script.sync_futures_daily_bars, script.sync_futures_market):
                with self.subTest(entry=sync.__name__):
                    with self.assertRaisesRegex(RuntimeError, "部分批次失败"):
                        sync()

    def test_menu_runs_full_sync_for_each_range(self):
        for choice, days in (("1", 60), ("2", 180), ("3", 365), ("4", 1095)):
            with self.subTest(choice=choice):
                with (
                    patch("builtins.input", return_value=f" {choice} "),
                    patch.object(script, "sync_futures_market", return_value={"contracts": 2, "rows": 10}) as sync,
                    redirect_stdout(io.StringIO()) as output,
                ):
                    script.main()
                sync.assert_called_once_with(lookback_days=days)
                self.assertIn("请选择要执行的任务", output.getvalue())

    def test_exit_and_invalid_input_never_create_service(self):
        for answer, message in ((" E ", "退出"), ("", "无效选项"), ("5", "无效选项")):
            with self.subTest(answer=answer):
                with (
                    patch("builtins.input", return_value=answer),
                    patch.object(script, "create_service") as factory,
                    redirect_stdout(io.StringIO()) as output,
                ):
                    script.main()
                factory.assert_not_called()
                self.assertIn(message, output.getvalue())
