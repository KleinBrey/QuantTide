"""数据库同步任务及各数据表的最新更新时间。"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

import requests
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from backend.app.jobs.tasks import database_sync_lock
from backend.app.schemas import SyncCryptoBars
from backend.app.schemas.watchlist import SyncGroupBars
from backend.scripts.sync_daily_bars import sync_daily_bars
from backend.scripts.sync_daily_basic import sync_daily_basic
from backend.scripts.sync_daily_stocks import sync_daily_stocks
from backend.scripts.sync_realtime_hot import sync_realtime_hot

from .dependencies import (
    CNMarketServiceDep,
    CryptoMarketServiceDep,
    CryptoRepository,
    DailyBasicRepo,
    DailyHotRepo,
    DailyRepository,
    DailyStockRepo,
    FuturesMarketServiceDep,
    FuturesRepository,
    HKDailyRepository,
    HKMarketServiceDep,
    HKStockHotRepository,
    USDailyRepository,
    USMarketServiceDep,
    USStockHotRepository,
    WatchlistServiceDep,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/watchlists/groups/{group_id}/sync-daily-bars", tags=["自选股"])
def sync_group_daily_bars(
    group_id: int,
    body: SyncGroupBars,
    watchlists: WatchlistServiceDep,
    cn: CNMarketServiceDep,
    hk: HKMarketServiceDep,
    us: USMarketServiceDep,
    crypto: CryptoMarketServiceDep,
    futures: FuturesMarketServiceDep,
) -> dict:
    """更新当前分组在当前市场的最近一年日 K，保留已成功写入的结果。"""
    if not database_sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有数据同步任务正在执行，请稍后重试")
    try:
        # 从分组实际成员确定范围，避免客户端传入其他分组的代码。
        items = watchlists.repository.list_items(group_id)
        symbols = [item["symbol"] for item in items if item["market"] == body.market]
        if not symbols:
            raise HTTPException(status_code=422, detail="当前分组在此市场没有可更新的资产")
        try:
            services = {"CN": cn, "HK": hk, "US": us, "CRYPTO": crypto, "FUTURES": futures}
            service = services[body.market]
            result = service.sync_group_daily_bars(symbols, lookback_days=365)
        except Exception as error:
            logger.exception("分组日 K 获取失败: group=%s market=%s", group_id, body.market)
            raise HTTPException(status_code=502, detail=f"获取当前分组最新日 K 失败：{error}") from error
        return {"group_id": group_id, "market": body.market, **result}
    finally:
        database_sync_lock.release()


@router.post("/crypto/sync", tags=["加密货币"], name="sync_daily_bars")
def sync_crypto_daily_bars(body: SyncCryptoBars, service: CryptoMarketServiceDep) -> dict:
    if not database_sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有数据同步任务正在执行，请稍后重试")
    try:
        count = service.sync_daily_bars(body.symbol, body.days)
    except requests.RequestException as error:
        raise HTTPException(
            status_code=502, detail="行情获取失败，请检查交易对代码和网络后重试"
        ) from error
    finally:
        database_sync_lock.release()
    return {"symbol": body.symbol, "rows": count}


async def _run_database_sync(
    script: str,
    success_message: str,
    task: Callable[[], None],
) -> dict[str, str | float]:
    """在线程池运行阻塞式同步脚本，并统一返回执行结果。"""

    if not database_sync_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409, detail="已有数据库同步任务正在执行，请稍后再试"
        )

    started_at = time.perf_counter()
    try:
        await run_in_threadpool(task)
    except Exception as error:
        logger.exception("数据库同步脚本执行失败: %s", script)
        raise HTTPException(
            status_code=500,
            detail=f"{script} 执行失败：{error}",
        ) from error
    finally:
        database_sync_lock.release()

    return {
        "status": "success",
        "script": script,
        "message": success_message,
        "duration_seconds": round(time.perf_counter() - started_at, 2),
        "finished_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
            timespec="seconds"
        ),
    }



@router.post("/database-sync/stock-list")
async def sync_daily_stocks_database() -> dict[str, str | float]:
    """执行股票列表数据库同步脚本。"""

    return await _run_database_sync(
        "sync_daily_stocks.py",
        "A 股股票列表同步完成",
        sync_daily_stocks,
    )



@router.post("/database-sync/daily-k")
async def sync_daily_bars_database() -> dict[str, str | float]:
    """执行最近 3 个自然日的日 K 数据库同步脚本。"""

    return await _run_database_sync(
        "sync_daily_bars.py",
        "最近 3 个自然日的日 K 数据同步完成",
        lambda: sync_daily_bars(lookback_days=3),
    )



@router.post("/database-sync/stock-daily-basic")
async def sync_daily_basic_database() -> dict[str, str | float]:
    """执行最新交易日股票指标数据库同步脚本。"""

    return await _run_database_sync(
        "sync_daily_basic.py",
        "最新交易日股票指标同步完成",
        lambda: sync_daily_basic(lookback_days=3),
    )



@router.post("/database-sync/hot-stock")
async def sync_realtime_hot_database() -> dict[str, str | float]:
    """执行实时股票热度数据库同步脚本。"""

    return await _run_database_sync(
        "sync_realtime_hot.py",
        "A 股、港股和美股实时股票热度同步完成",
        sync_realtime_hot,
    )



@router.get("/database-sync/latest-update-times")
def database_latest_update_times(
    daily_stock_repository: DailyStockRepo,
    daily_basic_repository: DailyBasicRepo,
    daily_repository: DailyRepository,
    daily_hot_repository: DailyHotRepo,
    hk_stock_hot_repository: HKStockHotRepository,
    us_stock_hot_repository: USStockHotRepository,
    hk_daily_repository: HKDailyRepository,
    us_daily_repository: USDailyRepository,
    futures_repository: FuturesRepository,
    crypto_repository: CryptoRepository,
) -> dict[str, datetime | None]:
    """返回各同步数据表的最新更新时间。"""

    return {
        "hot-stock": daily_hot_repository.get_latest_update_time(),
        "hk-hot-stock": hk_stock_hot_repository.get_latest_update_time(),
        "us-hot-stock": us_stock_hot_repository.get_latest_update_time(),
        "daily-k": daily_repository.get_latest_update_time(),
        "hk-daily-k": hk_daily_repository.get_latest_update_time(),
        "us-daily-k": us_daily_repository.get_latest_update_time(),
        "futures-daily-k": futures_repository.get_latest_update_time(),
        "crypto-daily-k": crypto_repository.get_latest_update_time(),
        "stock-daily-basic": daily_basic_repository.get_latest_update_time(),
        "stock-list": daily_stock_repository.get_latest_update_time(),
    }

