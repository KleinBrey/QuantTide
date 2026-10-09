"""并发请求工具的线程、限速、异常和资源释放验证。"""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.app.utils import concurrency
from backend.app.utils.concurrency import concurrent_requests
from backend.app.services import CNMarketService


class ConcurrentRequestsTests(unittest.TestCase):
    def test_ten_requests_overlap_with_limiter_and_results_stay_on_caller(self):
        lock = threading.Lock()
        barrier = threading.Barrier(10, timeout=5)
        active = peak = 0
        worker_ids = set()
        caller = threading.get_ident()

        def fetch(item):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                worker_ids.add(threading.get_ident())
            # Ten workers must enter fetch together; holding the limiter lock
            # during fetch would break this barrier.
            barrier.wait()
            with lock:
                active -= 1
            return item * 2

        results = {}
        with concurrent_requests(range(20), fetch, max_workers=10,
                                 request_interval=0.005, thread_name_prefix="test-overlap") as completed:
            for item, future in completed:
                self.assertEqual(threading.get_ident(), caller)
                results[item] = future.result()
        self.assertEqual(peak, 10)
        self.assertEqual(len(worker_ids), 10)
        self.assertNotIn(caller, worker_ids)
        self.assertEqual(results, {i: i * 2 for i in range(20)})
        self.assertFalse(any(t.name.startswith("test-overlap") for t in threading.enumerate()))

    def test_fixed_and_random_start_intervals(self):
        for interval, expected_gap in [(0.6, 0.6), ((0.5, 1.0), 0.75)]:
            with self.subTest(interval=interval):
                now = [0.0]
                starts = []
                def wait(seconds):
                    now[0] += seconds
                    return False
                def fetch(item):
                    starts.append(now[0])
                    now[0] += 0.2
                    return item
                clock = SimpleNamespace(monotonic=lambda: now[0])
                stop = Mock(wraps=threading.Event())
                stop.wait.side_effect = wait
                with patch.object(concurrency, "time", clock), patch.object(concurrency, "Event", return_value=stop), patch.object(concurrency.random, "uniform", return_value=0.75):
                    with concurrent_requests(range(3), fetch, max_workers=1,
                                             request_interval=interval) as completed:
                        self.assertEqual(sorted(f.result() for _, f in completed), [0, 1, 2])
                for actual, expected in zip(starts, [0, expected_gap, expected_gap * 2]):
                    self.assertAlmostEqual(actual, expected)
                self.assertEqual(stop.wait.call_count, 2)

    def test_fast_result_arrives_before_slow_result(self):
        release = threading.Event()
        def fetch(item):
            if item == "slow":
                if not release.wait(5):
                    raise TimeoutError("slow request was never released")
            return item
        with concurrent_requests(["slow", "fast"], fetch, request_interval=0) as completed:
            try:
                item, future = next(completed)
                self.assertEqual(item, "fast")
                self.assertEqual(future.result(), "fast")
            finally:
                release.set()
            self.assertEqual([(item, f.result()) for item, f in completed], [("slow", "slow")])

    def test_failure_retains_item_and_other_results(self):
        def fetch(item):
            if item == 1:
                raise ValueError("request failed")
            return item
        successes, failures = [], []
        with concurrent_requests(range(4), fetch, request_interval=0) as completed:
            for item, future in completed:
                try:
                    successes.append(future.result())
                except ValueError:
                    failures.append(item)
        self.assertEqual(sorted(successes), [0, 2, 3])
        self.assertEqual(failures, [1])

    def test_empty_input_and_invalid_options_do_not_create_pool(self):
        with patch.object(concurrency, "ThreadPoolExecutor") as executor:
            with concurrent_requests([], lambda item: item) as completed:
                self.assertEqual(list(completed), [])
            for kwargs in [{"max_workers": 0}, {"request_interval": -1},
                           {"request_interval": (1, 0.5)}, {"request_interval": float("nan")}]:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    with concurrent_requests([1], lambda item: item, **kwargs):
                        pass
            executor.assert_not_called()

    def test_consumer_exception_shuts_down_workers(self):
        with self.assertRaisesRegex(RuntimeError, "write failed"):
            with concurrent_requests(range(20), lambda item: item, request_interval=0,
                                     thread_name_prefix="test-cleanup") as completed:
                next(completed)
                raise RuntimeError("write failed")
        self.assertFalse(any(t.name.startswith("test-cleanup") for t in threading.enumerate()))

    def test_exit_wakes_waiting_workers_without_sending_more_requests(self):
        for consumer_error in [False, True]:
            with self.subTest(consumer_error=consumer_error):
                stop = threading.Event()
                waiting = threading.Event()
                observed_stop = Mock(wraps=stop)
                def wait(seconds):
                    waiting.set()
                    return stop.wait(seconds)
                observed_stop.wait.side_effect = wait
                calls, errors = [], []

                def run():
                    try:
                        with concurrent_requests(range(20), lambda item: calls.append(item),
                                                 request_interval=30) as completed:
                            _, future = next(completed)
                            future.result()
                            self.assertTrue(waiting.wait(2))
                            if consumer_error:
                                raise RuntimeError("consumer failed")
                    except RuntimeError as error:
                        if not consumer_error or str(error) != "consumer failed":
                            errors.append(error)
                    except BaseException as error:
                        errors.append(error)

                with patch.object(concurrency, "Event", return_value=observed_stop):
                    runner = threading.Thread(target=run, daemon=True)
                    runner.start()
                    runner.join(timeout=2)
                    still_running = runner.is_alive()
                    # 失败时也清理线程，不让 30 秒等待拖住测试进程。
                    stop.set()
                    runner.join(timeout=2)
                self.assertFalse(still_running, "退出仍被限速等待阻塞")
                self.assertFalse(errors, errors)
                self.assertEqual(calls, [0])

    def test_delayed_wakeup_does_not_catch_up_reserved_slots(self):
        now, starts = [0.0], []
        stop = Mock(wraps=threading.Event())
        def wait(seconds):
            # 第二次请求延迟唤醒 0.3 秒，第三次仍必须从实际放行时刻计算间隔。
            now[0] += seconds + (0.3 if len(starts) == 1 else 0)
            return False
        def fetch(item):
            starts.append(now[0])
            return item
        stop.wait.side_effect = wait
        with patch.object(concurrency, "time", SimpleNamespace(monotonic=lambda: now[0])), patch.object(concurrency, "Event", return_value=stop):
            with concurrent_requests(range(3), fetch, max_workers=1,
                                     request_interval=0.6) as completed:
                self.assertEqual(sorted(f.result() for _, f in completed), [0, 1, 2])
        for actual, expected in zip(starts, [0, 0.9, 1.5]):
            self.assertAlmostEqual(actual, expected)

    def test_daily_basic_requests_in_workers_and_writes_in_caller(self):
        caller = threading.get_ident()
        provider, repository = Mock(), Mock()
        daily_basic = SimpleNamespace(empty=False)
        def fetch(day):
            self.assertNotEqual(threading.get_ident(), caller)
            return daily_basic
        def upsert(rows):
            self.assertEqual(threading.get_ident(), caller)
            self.assertIs(rows, daily_basic)
            return 1
        provider.fetch_daily_basic.side_effect = fetch
        repository.upsert_stock_daily_basic.side_effect = upsert
        service = CNMarketService(tushare_provider=provider, daily_basic_repository=repository)
        self.assertEqual(service.update_daily_basic(), 1)
        provider.fetch_daily_basic.assert_called_once_with(None)


if __name__ == "__main__":
    unittest.main()
