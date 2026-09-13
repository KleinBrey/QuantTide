"""使用 Futu 同步港股和美股股票池的历史日 K 数据。"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from backend.app.config.config import get_settings
from backend.app.database import DuckDBDatabase, HKDuckDBDatabase, USDuckDBDatabase
from backend.app.provider import FutuProvider
from backend.app.repository import (
    HKDailyBarRepository,
    HKStockRepository,
    USDailyBarRepository,
    USStockRepository,
)


def format_futu_daily_bars(
    symbol: str,
    result: dict[str, dict[str, list[dict[str, Any]]]],
) -> pd.DataFrame:
    """将 Futu 历史行情转换为 ``daily_bars`` 表结构。"""

    columns = [
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "source",
    ]
    items = result.get("data", {}).get("item", [])
    frame = pd.DataFrame(items)
    if frame.empty:
        return pd.DataFrame(columns=columns)

    required_columns = [
        "date_ms",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
    ]
    missing_columns = [
        column for column in required_columns if column not in frame.columns
    ]
    if missing_columns:
        raise ValueError(f"Futu 日 K 数据缺少字段：{', '.join(missing_columns)}")

    frame["symbol"] = str(symbol).strip().upper()
    frame["trade_date"] = (
        pd.to_datetime(frame["date_ms"], unit="ms", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.date
    )
    frame["open"] = pd.to_numeric(frame["open_price"], errors="raise")
    frame["high"] = pd.to_numeric(frame["high_price"], errors="raise")
    frame["low"] = pd.to_numeric(frame["low_price"], errors="raise")
    frame["close"] = pd.to_numeric(frame["close_price"], errors="raise")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="raise")
    frame["amount"] = pd.to_numeric(frame["turnover"], errors="coerce")
    if "source" not in frame.columns:
        frame["source"] = FutuProvider.source
    else:
        frame["source"] = frame["source"].fillna(FutuProvider.source)

    return frame[columns].reset_index(drop=True)


def sync_market_daily_k(
    database: DuckDBDatabase,
    stock_repository: HKStockRepository | USStockRepository,
    daily_repository: HKDailyBarRepository | USDailyBarRepository,
    provider: FutuProvider,
    market_name: str,
    lookback_days: int,
    max_workers: int = 4,
    request_interval: float = 0.5,
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """同步单个市场 ``stocks`` 表内全部股票的历史日 K。"""

    if lookback_days <= 0:
        raise ValueError("lookback_days 必须大于 0")
    if max_workers <= 0:
        raise ValueError("max_workers 必须大于 0")
    if request_interval < 0:
        raise ValueError("request_interval 不能小于 0")

    database.initialize()
    stocks = stock_repository.get_table_data()
    symbols = stocks["symbol"].astype("string").dropna().tolist()
    if not symbols:
        print(f"{market_name} stocks 表为空，跳过日 K 同步")
        return {"stocks": 0, "rows": 0, "failed_symbols": []}

    end = now_ms if now_ms is not None else int(time.time() * 1000)
    start = end - lookback_days * 24 * 60 * 60 * 1000
    request_lock = threading.Lock()
    last_request_time = 0.0

    def fetch_symbol(symbol: str):
        nonlocal last_request_time

        # Futu 历史行情接口一次只接受一只股票；统一控制请求起始间隔，
        # 同时允许已发出的请求并行等待 OpenD 返回。
        with request_lock:
            now = time.monotonic()
            wait_time = request_interval - (now - last_request_time)
            if wait_time > 0:
                time.sleep(wait_time)
            last_request_time = time.monotonic()

        return provider.fetch_historical(
            symbol,
            start,
            end,
            interval="1d",
            adjust="forward",
        )

    failed_symbols: list[str] = []
    affected_rows = 0

    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix=f"{market_name}-daily-bar",
    ) as executor:
        futures = {
            executor.submit(fetch_symbol, symbol): symbol for symbol in symbols
        }

        for completed, future in enumerate(as_completed(futures), start=1):
            symbol = futures[future]
            try:
                rows = format_futu_daily_bars(symbol, future.result())
                # 与 A 股同步保持一致，不保存没有成交量的行情。
                rows = rows[rows["volume"].notna() & rows["volume"].ne(0)]
                affected_rows += daily_repository.upsert_daily_bars(rows)
            except Exception as error:
                failed_symbols.append(symbol)
                print(f"{market_name} {symbol} 获取失败: {error}", flush=True)

            if completed % 5 == 0 or completed == len(futures):
                print(
                    f"{market_name}日 K 进度：{completed}/{len(futures)}",
                    flush=True,
                )

    print(
        f"{market_name}日 K 同步完成：股票 {len(symbols)} 只，"
        f"写入 {affected_rows} 条，失败 {len(failed_symbols)} 只"
    )
    return {
        "stocks": len(symbols),
        "rows": affected_rows,
        "failed_symbols": sorted(failed_symbols),
    }


def sync_hk_us_daily_k(
    lookback_days: int,
    max_workers: int | None = None,
    request_interval: float = 0.5,
    *,
    provider: FutuProvider | None = None,
    hk_database: DuckDBDatabase | None = None,
    us_database: DuckDBDatabase | None = None,
) -> dict[str, dict[str, Any]]:
    """从港股和美股 ``stocks`` 表同步历史日 K。"""

    settings = get_settings()
    workers = max_workers if max_workers is not None else settings.sync_workers
    if provider is None:
        # Futu SDK 默认会为每次连接和断开打印日志，与动态终端输出叠加时
        # 会导致界面持续闪烁。CLI 中关闭控制台日志，接口错误仍会在下方汇总。
        FutuProvider.set_console_logging(False)
        futu_provider = FutuProvider()
    else:
        futu_provider = provider
    hk_db = hk_database or HKDuckDBDatabase(settings.hk_database_path)
    us_db = us_database or USDuckDBDatabase(settings.us_database_path)

    # 港股和美股共享一个 OpenD 行情连接，避免每只股票反复连接和断开。
    with futu_provider.session():
        return {
            "hk": sync_market_daily_k(
                hk_db,
                HKStockRepository(hk_db),
                HKDailyBarRepository(hk_db),
                futu_provider,
                "港股",
                lookback_days,
                workers,
                request_interval,
            ),
            "us": sync_market_daily_k(
                us_db,
                USStockRepository(us_db),
                USDailyBarRepository(us_db),
                futu_provider,
                "美股",
                lookback_days,
                workers,
                request_interval,
            ),
        }


def main() -> None:
    print("""
            请选择要执行的任务：

            1. 更新港股和美股最近 3 日数据
            2. 更新港股和美股最近 60 日数据
            3. 更新港股和美股最近 365 日数据
            e. 退出
          """)

    choice = input("请输入选项: ").strip().lower()
    lookback_days_by_choice = {"1": 3, "2": 60, "3": 365}

    if choice == "e":
        print("退出")
        return
    if choice not in lookback_days_by_choice:
        print(f"无效选项: {choice}")
        return

    sync_hk_us_daily_k(lookback_days_by_choice[choice])


if __name__ == "__main__":
    main()
