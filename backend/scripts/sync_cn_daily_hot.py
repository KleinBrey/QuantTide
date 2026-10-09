"""获取 A 股历史热度排名；通过 lookback_days 指定自然日范围。"""

import argparse
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from backend.app.config.config import get_settings
from backend.app.database import DuckDBDatabase
from backend.app.provider.hithink_provider import HithinkProvider
from backend.app.repository import DailyHotRepository, DailyStockRepository
from backend.app.utils.progress import progress_bar, progress_write


def fetch_daily_hot(symbol: str, name: str, start: str, end: str) -> pd.DataFrame:
    """在线程中等待并获取数据；数据库统一由主线程写入。"""
    time.sleep(random.uniform(1.0, 2.0))
    items = HithinkProvider().fetch_hot_stock_rank_trend(symbol, start, end)
    rows = pd.DataFrame(items)
    if rows.empty:
        return rows
    rows = rows.rename(columns={"date": "trade_date"})
    rows = rows.loc[rows["trade_date"].between(start, end)].copy()
    rows["symbol"] = symbol
    rows["name"] = name
    # 该接口只提供排名，不用当前价格填充历史行情。
    rows["price"] = None
    rows["change_pct"] = None
    rows["source"] = "Hithink"
    return rows


def sync_cn_daily_hot(lookback_days: int = 365) -> int:
    """补齐最近指定自然日范围（含今天）的热度排名。"""
    if lookback_days <= 0:
        raise ValueError("lookback_days 必须大于 0")

    settings = get_settings()
    database = DuckDBDatabase(settings.database_path)
    database.initialize()
    end = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    start = end - timedelta(days=lookback_days - 1)
    daily_stock_repository = DailyStockRepository(database)
    symbols = daily_stock_repository.get_symbols_in_range(start, end)
    if not symbols:
        raise RuntimeError("区间内股票池为空，请先补齐历史 daily_stocks")
    history = daily_stock_repository.get_table_data()
    history["trade_date"] = pd.to_datetime(history["trade_date"])
    snapshot_dates = history[["trade_date"]].drop_duplicates().rename(
        columns={"trade_date": "snapshot_date"}
    ).sort_values("snapshot_date")
    names = {
        symbol: group[["trade_date", "name"]].rename(columns={"trade_date": "snapshot_date"})
        for symbol, group in history.groupby("symbol")
    }
    repository = DailyHotRepository(database)
    total = 0
    failed, empty = [], []
    with ThreadPoolExecutor(max_workers=settings.sync_workers) as executor:
        futures = {
            executor.submit(
                fetch_daily_hot,
                symbol,
                symbol,
                start.isoformat(),
                end.isoformat(),
            ): symbol
            for symbol in symbols
        }
        progress = progress_bar(
            as_completed(futures),
            total=len(futures),
            desc="同步历史热度",
            unit="只",
            range_text=f"{start} 至 {end}",
            workers=settings.sync_workers,
        )
        for future in progress:
            symbol = futures[future]
            try:
                rows = future.result()
                if rows.empty:
                    empty.append(symbol)
                    continue
                # 热度中的名称也使用该日股票池；不能把当前名称填回历史。
                rows = rows.drop(columns="name")
                rows["trade_date"] = pd.to_datetime(rows["trade_date"])
                rows = pd.merge_asof(
                    rows.sort_values("trade_date"), snapshot_dates,
                    left_on="trade_date", right_on="snapshot_date", direction="backward",
                ).merge(names[symbol], on="snapshot_date", how="inner").drop(columns="snapshot_date")
                total += repository.fill_stock_hot_daily(rows)
            except Exception as exc:
                failed.append(symbol)
                progress_write(f"{symbol} 同步失败：{exc}")

    progress.finish(written=total, failed=len(failed), empty=len(empty))
    if empty:
        print("无数据股票：" + ", ".join(empty))
    if failed:
        print("失败股票：" + ", ".join(failed))
    if failed:
        raise RuntimeError("同步未完全完成，请查看以上失败记录；可重跑覆盖同步")
    return total


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="获取 A 股历史热度排名")
    parser.add_argument("--lookback-days", type=int, help="同步最近多少个自然日（含今天）")
    args = parser.parse_args(argv)
    days = args.lookback_days
    # 不传命令行参数时显示菜单；API 和定时任务直接调用同步函数。
    if days is None:
        print("""
            请选择要执行的任务：

            1. 更新最近 60 日A 股热度排名
            2. 更新最近 365 日A 股热度排名
            e. 退出
          """)
        choice = input("请输入选项: ").strip().lower()
        if choice == "e":
            print("退出")
            return
        days = {"1": 60, "2": 365}.get(choice)
        if days is None:
            print(f"无效选项: {choice}")
            return
    sync_cn_daily_hot(lookback_days=days)


if __name__ == "__main__":
    main()
