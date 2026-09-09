from __future__ import annotations

import logging
import threading
import time
from datetime import date
from datetime import datetime
from typing import Annotated, Callable
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from starlette.concurrency import run_in_threadpool

from backend.app.repository import (
    DailyBarRepository,
    HKStockHotDailyRepository,
    StockHotDailyRepository,
    StockDailyBasicRepository,
    StockRepository,
    USStockHotDailyRepository,
)
from backend.app.schemas import DailyBar, HotStock, Stock
from backend.app.services import Service
from backend.app.strategy.registry import (
    STRATEGY_EXECUTORS,
    execute_strategy,
    strategy_list,
)
from backend.app.strategy.result import format_strategy_result
from backend.app.utils.symbol import validate_symbol
from backend.scripts.sync_daily_k_db import sync_daily_k
from backend.scripts.sync_hot_stock_db import sync_stock_hot
from backend.scripts.sync_stock_daily_basic_db import sync_stock_daily_basic
from backend.scripts.sync_stock_list_db import sync_stock_list

from .dependencies import (
    get_daily_repository,
    get_hk_stock_hot_repository,
    get_service,
    get_stock_daily_basic_repository,
    get_stock_hot_repository,
    get_stock_repository,
    get_us_stock_hot_repository,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# DuckDB 只允许一个同步任务写入，避免用户连续点击导致写入互相冲突。
database_sync_lock = threading.Lock()

# 使用 Annotated 封装依赖声明，避免每个接口重复书写 Depends。
StockListRepository = Annotated[StockRepository, Depends(get_stock_repository)]
DailyRepository = Annotated[DailyBarRepository, Depends(get_daily_repository)]
StockDailyBasicRepo = Annotated[
    StockDailyBasicRepository,
    Depends(get_stock_daily_basic_repository),
]
StockHotRepository = Annotated[
    StockHotDailyRepository,
    Depends(get_stock_hot_repository),
]
HKStockHotRepository = Annotated[
    HKStockHotDailyRepository,
    Depends(get_hk_stock_hot_repository),
]
USStockHotRepository = Annotated[
    USStockHotDailyRepository,
    Depends(get_us_stock_hot_repository),
]
dbService = Annotated[Service, Depends(get_service)]


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
async def sync_stock_list_database() -> dict[str, str | float]:
    """执行股票列表数据库同步脚本。"""

    return await _run_database_sync(
        "sync_stock_list_db.py",
        "A 股股票列表同步完成",
        sync_stock_list,
    )


@router.post("/database-sync/daily-k")
async def sync_daily_k_database() -> dict[str, str | float]:
    """执行最近 3 个自然日的日 K 数据库同步脚本。"""

    return await _run_database_sync(
        "sync_daily_k_db.py",
        "最近 3 个自然日的日 K 数据同步完成",
        lambda: sync_daily_k(lookback_days=3, batch_size=100),
    )


@router.post("/database-sync/stock-daily-basic")
async def sync_stock_daily_basic_database() -> dict[str, str | float]:
    """执行最新交易日股票指标数据库同步脚本。"""

    return await _run_database_sync(
        "sync_stock_daily_basic_db.py",
        "最新交易日股票指标同步完成",
        sync_stock_daily_basic,
    )


@router.post("/database-sync/hot-stock")
async def sync_hot_stock_database() -> dict[str, str | float]:
    """执行每日股票热度数据库同步脚本。"""

    return await _run_database_sync(
        "sync_hot_stock_db.py",
        "A 股、港股和美股每日热度同步完成",
        sync_stock_hot,
    )


@router.get("/database-sync/latest-update-times")
def database_latest_update_times(
    stock_repository: StockListRepository,
    stock_daily_basic_repository: StockDailyBasicRepo,
    daily_repository: DailyRepository,
    stock_hot_repository: StockHotRepository,
    hk_stock_hot_repository: HKStockHotRepository,
    us_stock_hot_repository: USStockHotRepository,
) -> dict[str, datetime | None]:
    """返回各同步数据表的最新更新时间。"""

    return {
        "hot-stock": stock_hot_repository.get_latest_update_time(),
        "hk-hot-stock": hk_stock_hot_repository.get_latest_update_time(),
        "us-hot-stock": us_stock_hot_repository.get_latest_update_time(),
        "daily-k": daily_repository.get_latest_update_time(),
        "stock-daily-basic": stock_daily_basic_repository.get_latest_update_time(),
        "stock-list": stock_repository.get_latest_update_time(),
    }


@router.get("/stocks-list", response_model=list[Stock])
def stocks(
    repository: StockListRepository,
) -> list[dict]:

    stock_table = repository.get_table_data().head(100)

    # FastAPI 不能直接把 DataFrame 当成“股票列表”返回。
    # orient="records" 会把每一行转换成一个字典，最终得到：
    # [{"symbol": "000001.SZ", "name": "平安银行", ...}, ...]
    stock_list = stock_table.to_dict(orient="records")
    return stock_list


@router.post("/stocks-list")
def update_stocks_list(service: dbService) -> dict[str, str]:
    """从数据源获取最新股票列表，并保存到本地数据库。"""

    service.update_stocks_list()

    # 只有上面的更新操作没有抛出异常时，才会执行到这里。
    return {
        "status": "success",
        "message": "股票列表更新成功",
    }


@router.get("/hot-stock", response_model=list[HotStock])
def hot_stock(service: dbService, count: int = 100) -> list[dict]:
    """返回最新 A 股热度榜；数据库缓存超过两小时时自动同步。"""

    hot_stock_table = service.get_hot_stock().head(count)
    # 将 pandas 的 NaN/NaT 转为 None，确保可选字段能被 JSON 正确编码。
    hot_stock_table = hot_stock_table.astype(object).where(
        pd.notna(hot_stock_table),
        None,
    )
    return hot_stock_table.to_dict(orient="records")


@router.get("/hk-hot-stock", response_model=list[HotStock])
def hk_hot_stock(service: dbService, count: int = 50) -> list[dict]:
    """返回最新港股热度榜；数据库缓存超过两小时时自动同步。"""

    hot_stock_table = service.get_hk_hot_stock().head(count)
    hot_stock_table = hot_stock_table.astype(object).where(
        pd.notna(hot_stock_table),
        None,
    )
    return hot_stock_table.to_dict(orient="records")


@router.get("/us-hot-stock", response_model=list[HotStock])
def us_hot_stock(service: dbService, count: int = 50) -> list[dict]:
    """返回最新美股热度榜；数据库缓存超过两小时时自动同步。"""

    hot_stock_table = service.get_us_hot_stock().head(count)
    hot_stock_table = hot_stock_table.astype(object).where(
        pd.notna(hot_stock_table),
        None,
    )
    return hot_stock_table.to_dict(orient="records")


@router.get("/daily-bars", response_model=list[DailyBar])
def daily_bars(
    repository: DailyRepository,
    symbol: Annotated[
        str,
        Query(description="股票代码，例如 600519 或 600519.SH"),
    ],
    start: Annotated[
        date,
        Query(description="开始日期，格式 YYYY-MM-DD，包含当天"),
    ],
    end: Annotated[
        date,
        Query(description="结束日期，格式 YYYY-MM-DD，包含当天"),
    ],
) -> list[dict]:
    """从本地数据库查询指定股票、指定日期范围内的日 K 线。"""

    if start > end:
        raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")

    try:
        normalized_symbol = validate_symbol(symbol)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    daily_bar_table = repository.get_by_symbol_and_date_range(
        normalized_symbol,
        start,
        end,
    )

    records = daily_bar_table.to_dict(orient="records")

    return records


@router.get("/strategies")
def strategies() -> dict[str, list[dict[str, object]]]:
    """返回策略列表"""

    return {"items": strategy_list()}


@router.get("/strategies/{strategy_id}/signals")
def strategy_signals(
    strategy_id: str,
    stock_repository: StockListRepository,
    daily_repository: DailyRepository,
    stock_daily_basic_repository: StockDailyBasicRepo,
    stock_hot_repository: StockHotRepository,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, object]:
    """执行指定策略并返回结果"""

    if strategy_id not in STRATEGY_EXECUTORS:
        raise HTTPException(status_code=404, detail="该策略不存在")

    try:
        selected_stocks = execute_strategy(
            strategy_id,
            stocks=stock_repository.get_table_data(),
            daily_bars=daily_repository.get_table_data(),
            hot_stocks=stock_hot_repository.get_latest(),
            stock_daily_basic=stock_daily_basic_repository.get_table_data(),
        )
    except Exception as error:
        logger.exception("执行策略 %s 失败", strategy_id)
        raise HTTPException(
            status_code=500,
            detail=f"策略执行失败：{error}",
        ) from error

    return format_strategy_result(strategy_id, selected_stocks, limit=limit)
