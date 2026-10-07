"""日常更新：同步最近 3 个自然日的数据，供历史入口复用同步函数。"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from backend.app.config.config import get_settings
from backend.app.database import DuckDBDatabase, HKDuckDBDatabase, USDuckDBDatabase, SQLiteDatabase
from backend.app.repository.watchlist import WatchlistRepository
from backend.app.provider import YFinanceProvider
from backend.app.utils.progress import progress_bar, progress_write
from backend.app.repository import (
    HKDailyBarRepository,
    HKStockRepository,
    USDailyBarRepository,
    USStockRepository,
)


def format_yfinance_daily_bars(
    symbol: str,
    result: dict[str, dict[str, list[dict[str, Any]]]],
) -> pd.DataFrame:
    """将 Yahoo Finance 历史行情转换为 ``daily_bars`` 表结构。"""

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
    ]
    missing_columns = [
        column for column in required_columns if column not in frame.columns
    ]
    if missing_columns:
        raise ValueError(
            f"Yahoo Finance 日 K 数据缺少字段：{', '.join(missing_columns)}"
        )

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
    # Yahoo 日线没有真实成交额，不以收盘价乘成交量替代。
    frame["amount"] = None
    if "source" not in frame.columns:
        frame["source"] = YFinanceProvider.source
    else:
        frame["source"] = frame["source"].fillna(YFinanceProvider.source)

    return frame[columns].reset_index(drop=True)


def sync_market_daily_k(
    database: DuckDBDatabase,
    stock_repository: HKStockRepository | USStockRepository,
    daily_repository: HKDailyBarRepository | USDailyBarRepository,
    provider: YFinanceProvider,
    market_name: str,
    lookback_days: int,
    max_workers: int = 4,
    request_interval: float = 0.5,
    *,
    now_ms: int | None = None,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """同步单个市场 ``stocks`` 表内全部股票的历史日 K。"""

    if lookback_days <= 0:
        raise ValueError("lookback_days 必须大于 0")
    if max_workers <= 0:
        raise ValueError("max_workers 必须大于 0")
    if request_interval < 0:
        raise ValueError("request_interval 不能小于 0")

    database.initialize()
    if symbols is None:
        stocks = stock_repository.get_table_data()
        symbols = stocks["symbol"].astype("string").dropna().tolist()
    if not symbols:
        print(f"{market_name}股票池为空，跳过日 K 同步")
        return {"stocks": 0, "rows": 0, "failed_symbols": []}

    end = now_ms if now_ms is not None else int(time.time() * 1000)
    start = end - lookback_days * 24 * 60 * 60 * 1000
    request_lock = threading.Lock()
    last_request_time = 0.0

    def fetch_symbol(symbol: str):
        nonlocal last_request_time

        # 统一控制 Yahoo 请求起始间隔，避免短时间集中请求。
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
        futures = {executor.submit(fetch_symbol, symbol): symbol for symbol in symbols}

        progress = progress_bar(
            as_completed(futures),
            total=len(futures),
            desc=f"同步{market_name}日 K",
            unit="只",
            range_text=f"{pd.Timestamp(start, unit='ms', tz='Asia/Shanghai').date()} 至 "
            f"{pd.Timestamp(end, unit='ms', tz='Asia/Shanghai').date()}",
            workers=max_workers,
        )
        for future in progress:
            symbol = futures[future]
            try:
                rows = format_yfinance_daily_bars(symbol, future.result())
                # 与 A 股同步保持一致，不保存没有成交量的行情。
                rows = rows[rows["volume"].notna() & rows["volume"].ne(0)]
                affected_rows += daily_repository.upsert_daily_bars(rows)
            except Exception as error:
                failed_symbols.append(symbol)
                progress_write(f"{market_name} {symbol} 获取失败: {error}")

    progress.finish(written=affected_rows, failed=len(failed_symbols))
    return {
        "stocks": len(symbols),
        "rows": affected_rows,
        "failed_symbols": sorted(failed_symbols),
    }


def sync_hk_us_daily_bars(
    lookback_days: int = 3,
    max_workers: int | None = None,
    request_interval: float = 0.5,
    *,
    provider: YFinanceProvider | None = None,
    hk_database: DuckDBDatabase | None = None,
    us_database: DuckDBDatabase | None = None,
    app_database: SQLiteDatabase | None = None,
) -> dict[str, dict[str, Any]]:
    """从 SQLite 中港股和美股 stock_pool 默认分组同步历史日 K。"""

    settings = get_settings()
    workers = (
        max_workers
        if max_workers is not None
        else min(settings.sync_workers, lookback_days)
    )
    quote_provider = provider if provider is not None else YFinanceProvider()
    hk_db = hk_database or HKDuckDBDatabase(settings.hk_database_path)
    us_db = us_database or USDuckDBDatabase(settings.us_database_path)
    hk_db.initialize()
    us_db.initialize()
    business_db = app_database or SQLiteDatabase(
        hk_db.database_path.parent / 'app.sqlite' if hk_database is not None else settings.app_database_path
    )
    business_db.initialize()
    watchlists = WatchlistRepository(business_db)
    watchlists.migrate_stock_pools(
        HKStockRepository(hk_db).get_table_data()['symbol'].tolist(),
        USStockRepository(us_db).get_table_data()['symbol'].tolist(),
    )

    def pool_symbols(market):
        return [row['symbol'] for row in watchlists.list_items(watchlists.get_pool(market)['id'])]

    return {
        "hk": sync_market_daily_k(
            hk_db,
            HKStockRepository(hk_db),
            HKDailyBarRepository(hk_db),
            quote_provider,
            "港股",
            lookback_days,
            workers,
            request_interval,
            symbols=pool_symbols('HK'),
        ),
        "us": sync_market_daily_k(
            us_db,
            USStockRepository(us_db),
            USDailyBarRepository(us_db),
            quote_provider,
            "美股",
            lookback_days,
            workers,
            request_interval,
            symbols=pool_symbols('US'),
        ),
    }


def main() -> None:
    sync_hk_us_daily_bars()


if __name__ == "__main__":
    main()
