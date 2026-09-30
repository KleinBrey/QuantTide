"""补齐 A 股股票池最近 365 个自然日的热度排名。"""

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from tqdm import tqdm

from backend.app.config.config import get_settings
from backend.app.database import DuckDBDatabase
from backend.app.provider.hithink_provider import HithinkProvider
from backend.app.repository import StockHotDailyRepository, StockRepository


def fetch_stock_rank(symbol: str, name: str, start: str, end: str) -> pd.DataFrame:
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


def sync_hot_stock_history() -> int:
    settings = get_settings()
    database = DuckDBDatabase(settings.database_path)
    database.initialize()
    stocks = StockRepository(database).get_table_data()
    if stocks.empty:
        raise RuntimeError("股票池为空，请先运行 backend.scripts.sync_stock_list")
    repository = StockHotDailyRepository(database)

    end = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    start = end - timedelta(days=364)
    print(
        f"同步 {len(stocks)} 只股票：{start} 至 {end}，并发数 {settings.sync_workers}"
    )
    total = 0
    failed, empty = [], []
    with ThreadPoolExecutor(max_workers=settings.sync_workers) as executor:
        futures = {
            executor.submit(
                fetch_stock_rank,
                stock.symbol,
                stock.name,
                start.isoformat(),
                end.isoformat(),
            ): stock.symbol
            for stock in stocks.itertuples(index=False)
        }
        for future in tqdm(
            as_completed(futures), total=len(futures), desc="同步历史热度"
        ):
            symbol = futures[future]
            try:
                rows = future.result()
                if rows.empty:
                    empty.append(symbol)
                    continue
                total += repository.fill_stock_hot_daily(rows)
            except Exception as exc:
                failed.append(symbol)
                tqdm.write(f"{symbol} 同步失败：{exc}")

    print(f"写入 {total} 条（含覆盖）；失败 {len(failed)} 只；无数据 {len(empty)} 只")
    if empty:
        print("无数据股票：" + ", ".join(empty))
    if failed:
        print("失败股票：" + ", ".join(failed))
    if failed:
        raise RuntimeError("同步未完全完成，请查看以上失败记录；可重跑覆盖同步")
    return total


def main() -> None:
    sync_hot_stock_history()


if __name__ == "__main__":
    main()
