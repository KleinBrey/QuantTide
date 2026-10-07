"""并发请求工具：统一管理线程池、请求启动间隔和任务完成顺序。"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Generator, Iterable, Iterator
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from threading import Event, Lock
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


@contextmanager
def concurrent_requests(
    items: Iterable[T],
    fetch: Callable[[T], R],
    *,
    max_workers: int = 10,
    request_interval: float | tuple[float, float] = (0.5, 1.0),
    thread_name_prefix: str = "request",
) -> Generator[Iterator[tuple[T, Future[R]]], None, None]:
    """按完成顺序返回 (原始任务, Future)，由调用线程处理结果和写库。

    必须通过 with 使用，退出时唤醒限速等待线程、取消未启动任务，
    并等待已经放行的请求结束（不能强行中断网络请求）。
    request_interval 为固定秒数或随机范围；0 表示不限制启动间隔。
    锁仅用于请求启动限速，fetch 在锁外执行，因此网络请求可以重叠。
    限速范围为本次调用，不跨同步任务或进程共享。异常由 future.result()
    重新抛出，交给业务层决定记录、重试或终止。

    max_workers 是并发上限，限速优先，并不保证所有线程一直在执行请求。
    平均启动间隔为 I > 0、平均 fetch 耗时为 T 时，稳定吞吐上限约为
    min(1 / I, max_workers / T)，平均在途数量约为实际吞吐乘以 T。
    默认 I 为 0.75 秒，限速吞吐上限约 1.33 次/秒；达到该上限后，继续
    增加线程通常不会提速。以上为稳态估算，耗时波动和任务数量会影响结果。
    """
    if max_workers <= 0:
        raise ValueError("max_workers 必须大于 0")
    lower, upper = (
        request_interval
        if isinstance(request_interval, tuple)
        else (request_interval, request_interval)
    )
    if not (math.isfinite(lower) and math.isfinite(upper) and 0 <= lower <= upper):
        raise ValueError("request_interval 必须是非负秒数或递增的有限范围")
    tasks = list(items)
    if not tasks:
        yield iter(())
        return

    stop = Event()
    request_lock = Lock()
    last_request_time: float | None = None

    def fetch_one(item: T) -> R:
        nonlocal last_request_time
        with request_lock:
            if stop.is_set():
                raise CancelledError()
            interval = lower if lower == upper else random.uniform(lower, upper)
            if last_request_time is not None:
                wait_time = interval - (time.monotonic() - last_request_time)
                if wait_time > 0 and stop.wait(wait_time):
                    raise CancelledError()
            if stop.is_set():
                raise CancelledError()
            # 记录实际放行时间；延迟唤醒后仍从此刻计算下一次间隔，不追赶预约时间。
            last_request_time = time.monotonic()
        if stop.is_set():
            raise CancelledError()
        return fetch(item)

    with ThreadPoolExecutor(
        max_workers=min(max_workers, len(tasks)),
        thread_name_prefix=thread_name_prefix,
    ) as executor:
        futures = {executor.submit(fetch_one, item): item for item in tasks}
        try:
            yield ((futures[future], future) for future in as_completed(futures))
        finally:
            # 不获取 request_lock，让锁内等待可以立即被唤醒并退出。
            stop.set()
            for future in futures:
                future.cancel()
