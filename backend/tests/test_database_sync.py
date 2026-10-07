"""验证页面同步入口，不调用真实行情接口或写入用户数据库。"""

import threading
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes


class DatabaseSyncTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(routes.router, prefix="/api")
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        lock_patch = patch.object(routes, "database_sync_lock", threading.Lock())
        self.lock = lock_patch.start()
        self.addCleanup(lock_patch.stop)
        self.results = {
            "hk": {"stocks": 1, "rows": 3, "failed_symbols": []},
            "us": {"stocks": 1, "rows": 3, "failed_symbols": []},
        }

    def test_hk_us_sync_runs_in_threadpool_and_returns_execution_details(self):
        execution_threads = []

        async def run_in_threadpool(task):
            event_loop_thread = threading.get_ident()
            from starlette.concurrency import run_in_threadpool as run
            result = await run(task)
            self.assertNotEqual(execution_threads[0], event_loop_thread)
            return result

        def sync(**kwargs):
            execution_threads.append(threading.get_ident())
            return self.results

        with (
            patch.object(routes, "sync_hk_us_daily_bars", side_effect=sync) as task,
            patch.object(routes, "run_in_threadpool", side_effect=run_in_threadpool),
        ):
            response = self.client.post("/api/database-sync/hk-us-daily-k")
        self.assertEqual(response.status_code, 200, response.text)
        task.assert_called_once_with(lookback_days=3)
        result = response.json()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["script"], "latest/sync_hk_us_daily_bars.py")
        self.assertGreaterEqual(result["duration_seconds"], 0)
        self.assertEqual(datetime.fromisoformat(result["finished_at"]).utcoffset().total_seconds(), 28800)
        self.assertFalse(self.lock.locked())

    def test_shared_lock_prevents_concurrent_sync(self):
        self.lock.acquire()
        self.addCleanup(self.lock.release)
        with patch.object(routes, "sync_hk_us_daily_bars") as task:
            for endpoint in ["hk-us-daily-k", "daily-k", "hot-stock", "stock-list", "stock-daily-basic"]:
                with self.subTest(endpoint=endpoint):
                    response = self.client.post(f"/api/database-sync/{endpoint}")
                    self.assertEqual(response.status_code, 409, response.text)
            task.assert_not_called()

    def test_script_errors_and_partial_failures_release_lock_for_retry(self):
        partial_results = {**self.results, "us": {"failed_symbols": ["AAPL"]}}
        for failure in [RuntimeError("行情接口不可用"), partial_results]:
            with self.subTest(failure=failure), patch.object(
                routes, "sync_hk_us_daily_bars", side_effect=[failure, self.results],
            ):
                response = self.client.post("/api/database-sync/hk-us-daily-k")
                self.assertEqual(response.status_code, 500, response.text)
                self.assertIn("latest/sync_hk_us_daily_bars.py", response.json()["detail"])
                if isinstance(failure, dict):
                    self.assertIn("AAPL", response.json()["detail"])
                self.assertFalse(self.lock.locked())
                self.assertEqual(self.client.post("/api/database-sync/hk-us-daily-k").status_code, 200)

    def test_latest_updates_include_both_markets_and_empty_tables(self):
        for attribute in [
            "daily_stock_repository", "daily_basic_repository", "daily_repository",
            "daily_hot_repository", "hk_stock_hot_repository", "us_stock_hot_repository",
            "hk_daily_repository", "us_daily_repository",
        ]:
            setattr(self.app.state, attribute, Mock(get_latest_update_time=Mock(return_value=None)))
        latest = datetime(2026, 10, 7, 10, 30)
        self.app.state.hk_daily_repository.get_latest_update_time.return_value = latest
        response = self.client.get("/api/database-sync/latest-update-times")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["hk-daily-k"], latest.isoformat())
        self.assertIsNone(response.json()["us-daily-k"])
        self.assertIsNone(response.json()["daily-k"])


if __name__ == "__main__":
    unittest.main()
