"""多线程同步历史股票池；可选近 60 日、近半年、近一年或近三年，每次拉取覆盖已有快照。"""

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tqdm import tqdm

from backend.app.config.config import get_settings
from backend.app.database import DuckDBDatabase
from backend.app.provider import TushareProvider
from backend.app.repository import DailyStockRepository
from backend.app.services import CNMarketService


def sync_stock_list_history(
    lookback_days: int = 365,
    *,
    workers: int | None = None,
) -> int:
    """重新拉取最近指定自然日（含今天）的股票池，按交易日完整替换。"""
    if lookback_days <= 0:
        raise ValueError("lookback_days 必须大于 0")
    settings = get_settings()
    max_workers = settings.sync_workers if workers is None else workers
    if max_workers <= 0:
        raise ValueError("workers 必须大于 0")
    end = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    start = end - timedelta(days=lookback_days - 1)
    if start < date(2016, 1, 1):
        raise ValueError("历史股票池范围必须从 2016-01-01 起")
    database = DuckDBDatabase(settings.database_path)
    database.initialize()
    provider = TushareProvider()
    days = provider.fetch_trade_dates(start, end)
    if not days:
        raise RuntimeError("指定区间的交易日历为空")
    print(f"覆盖同步股票池：{start} 至 {end}，共 {len(days)} 个交易日，并发数 {max_workers}")
    repository = DailyStockRepository(database)
    lock = threading.Lock()
    last_request = 0.0

    def fetch(day: date):
        nonlocal last_request
        # 仅对请求启动时间限速；网络请求并行执行，数据库由主线程写入。
        with lock:
            time.sleep(max(0, 0.6 - (time.monotonic() - last_request)))
            last_request = time.monotonic()
        return CNMarketService.format_stock_list(provider.fetch_stock_list(day), "Tushare")

    total, failures = 0, []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch, day): day for day in days}
        for future in tqdm(as_completed(futures), total=len(futures), desc="历史股票池", unit="日"):
            day = futures[future]
            try:
                total += repository.upsert_stocks(future.result())
            except Exception as error:
                failures.append(day)
                tqdm.write(f"{day} 同步失败：{error}")
    print(f"股票池写入 {total} 条（含覆盖），失败 {len(failures)} 日")
    if failures:
        raise RuntimeError("历史股票池未完整同步，可重跑覆盖同步：" + ", ".join(map(str, failures)))
    return total


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("必须是大于 0 的整数")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, choices=[60, 180, 365, 1095], help="最近自然日数（含今天）")
    parser.add_argument("--workers", type=positive_int, help="并发线程数，默认使用 sync_workers 配置")
    args = parser.parse_args()
    lookback_days = args.lookback_days
    if lookback_days is None:
        print("""
            请选择要执行的任务：

            1. 更新最近 60 日股票池
            2. 更新近半年股票池（180 日）
            3. 更新近一年股票池（365 日）
            4. 更新近三年股票池（1095 日）
            e. 退出
          """)
        choice = input("请输入选项: ").strip().lower()
        if choice == "e":
            print("退出")
            return
        lookback_days = {"1": 60, "2": 180, "3": 365, "4": 1095}.get(choice)
        if lookback_days is None:
            print(f"无效选项: {choice}")
            return
    sync_stock_list_history(lookback_days=lookback_days, workers=args.workers)


if __name__ == "__main__":
    main()
