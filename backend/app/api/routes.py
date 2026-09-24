from __future__ import annotations

import logging
import threading
import time
from datetime import date
from datetime import datetime
from typing import Annotated, Callable, Literal
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
    HKDailyBarRepository,
    HKStockHotDailyRepository,
    HKStockRepository,
    StockHotDailyRepository,
    StockDailyBasicRepository,
    StockRepository,
    USDailyBarRepository,
    USStockHotDailyRepository,
    USStockRepository,
)
from backend.app.schemas import DailyBar, HotStock, GlobalStock, Stock
from backend.app.services import CNMarketService, HKMarketService, USMarketService
from backend.quant.signal.registry import (
    SIGNAL_EXECUTORS,
    execute_signal,
    find_signal,
    signal_list,
)
from backend.quant.backtest.engine import (
    BacktestConfig,
    ConfirmedVolumeBreakoutBacktest,
)
from backend.quant.backtest.result import format_backtest_result
from backend.quant.signal.result import format_signal_result
from backend.app.utils.symbol import normalize_daily_bar_symbol
from backend.scripts.sync_daily_k_db import sync_daily_k
from backend.scripts.sync_hot_stock_db import sync_stock_hot
from backend.scripts.sync_stock_daily_basic_db import sync_stock_daily_basic
from backend.scripts.sync_stock_list_db import sync_stock_list

from .dependencies import (
    get_daily_repository,
    get_cn_market_service,
    get_hk_daily_repository,
    get_hk_market_service,
    get_hk_stock_repository,
    get_hk_stock_hot_repository,
    get_stock_daily_basic_repository,
    get_stock_hot_repository,
    get_stock_repository,
    get_us_market_service,
    get_us_stock_repository,
    get_us_stock_hot_repository,
    get_us_daily_repository,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# DuckDB 只允许一个同步任务写入，避免用户连续点击导致写入互相冲突。
database_sync_lock = threading.Lock()

# 使用 Annotated 封装依赖声明，避免每个接口重复书写 Depends。
StockListRepository = Annotated[StockRepository, Depends(get_stock_repository)]
HKStockListRepository = Annotated[
    HKStockRepository,
    Depends(get_hk_stock_repository),
]
USStockListRepository = Annotated[
    USStockRepository,
    Depends(get_us_stock_repository),
]
DailyRepository = Annotated[DailyBarRepository, Depends(get_daily_repository)]
HKDailyRepository = Annotated[
    HKDailyBarRepository,
    Depends(get_hk_daily_repository),
]
USDailyRepository = Annotated[
    USDailyBarRepository,
    Depends(get_us_daily_repository),
]
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
CNMarketServiceDep = Annotated[
    CNMarketService,
    Depends(get_cn_market_service),
]
HKMarketServiceDep = Annotated[
    HKMarketService,
    Depends(get_hk_market_service),
]
USMarketServiceDep = Annotated[
    USMarketService,
    Depends(get_us_market_service),
]


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
        lambda: sync_stock_daily_basic(lookback_days=3),
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


@router.get("/market-stocks", response_model=list[GlobalStock])
def market_stocks(
    hk_repository: HKStockListRepository,
    us_repository: USStockListRepository,
    market: Annotated[
        Literal["hk-share", "us-share"],
        Query(description="股票池所在的市场数据库"),
    ],
) -> list[dict]:
    """返回港股或美股数据库 ``stocks`` 表的全部记录。"""

    repositories = {
        "hk-share": hk_repository,
        "us-share": us_repository,
    }
    stock_table = repositories[market].get_table_data()
    return stock_table.to_dict(orient="records")


@router.post("/stocks-list")
def update_stocks_list(cn_market_service: CNMarketServiceDep) -> dict[str, str]:
    """从数据源获取最新股票列表，并保存到本地数据库。"""

    cn_market_service.update_stocks_list()

    # 只有上面的更新操作没有抛出异常时，才会执行到这里。
    return {
        "status": "success",
        "message": "股票列表更新成功",
    }


@router.get("/hot-stock", response_model=list[HotStock])
def hot_stock(cn_market_service: CNMarketServiceDep, count: int = 100) -> list[dict]:
    """返回最新 A 股热度榜；数据库缓存超过两小时时自动同步。"""

    hot_stock_table = cn_market_service.get_hot_stock().head(count)
    # 将 pandas 的 NaN/NaT 转为 None，确保可选字段能被 JSON 正确编码。
    hot_stock_table = hot_stock_table.astype(object).where(
        pd.notna(hot_stock_table),
        None,
    )
    return hot_stock_table.to_dict(orient="records")


@router.get("/hk-hot-stock", response_model=list[HotStock])
def hk_hot_stock(hk_market_service: HKMarketServiceDep, count: int = 50) -> list[dict]:
    """返回最新港股热度榜；数据库缓存超过两小时时自动同步。"""

    hot_stock_table = hk_market_service.get_hot_stock().head(count)
    hot_stock_table = hot_stock_table.astype(object).where(
        pd.notna(hot_stock_table),
        None,
    )
    return hot_stock_table.to_dict(orient="records")


@router.get("/us-hot-stock", response_model=list[HotStock])
def us_hot_stock(us_market_service: USMarketServiceDep, count: int = 50) -> list[dict]:
    """返回最新美股热度榜；数据库缓存超过两小时时自动同步。"""

    hot_stock_table = us_market_service.get_hot_stock().head(count)
    hot_stock_table = hot_stock_table.astype(object).where(
        pd.notna(hot_stock_table),
        None,
    )
    return hot_stock_table.to_dict(orient="records")


@router.get("/daily-bars", response_model=list[DailyBar])
def daily_bars(
    repository: DailyRepository,
    hk_repository: HKDailyRepository,
    us_repository: USDailyRepository,
    symbol: Annotated[
        str,
        Query(description="股票代码，例如 600519.SH、0700.HK 或 NVDA.O"),
    ],
    start: Annotated[
        date,
        Query(description="开始日期，格式 YYYY-MM-DD，包含当天"),
    ],
    end: Annotated[
        date,
        Query(description="结束日期，格式 YYYY-MM-DD，包含当天"),
    ],
    market: Annotated[
        Literal["a-share", "hk-share", "us-share"],
        Query(description="日 K 所在市场数据库"),
    ] = "a-share",
) -> list[dict]:
    """按市场从对应 DuckDB 查询指定日期范围内的日 K 线。"""

    if start > end:
        raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")

    try:
        normalized_symbol = normalize_daily_bar_symbol(symbol, market)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    repositories = {
        "a-share": repository,
        "hk-share": hk_repository,
        "us-share": us_repository,
    }
    daily_bar_table = repositories[market].get_by_symbol_and_date_range(
        normalized_symbol,
        start,
        end,
    )

    records = daily_bar_table.to_dict(orient="records")

    return records


@router.get("/signals")
def signals() -> dict[str, list[dict[str, object]]]:
    """返回选股信号列表。"""

    return {"items": signal_list()}


@router.get("/signals/{signal_id}")
def signal_results(
    signal_id: str,
    stock_repository: StockListRepository,
    daily_repository: DailyRepository,
    stock_daily_basic_repository: StockDailyBasicRepo,
    stock_hot_repository: StockHotRepository,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, object]:
    """运行指定形态识别器并返回命中结果。"""

    if signal_id not in SIGNAL_EXECUTORS:
        raise HTTPException(status_code=404, detail="该信号不存在")

    try:
        selected_stocks = execute_signal(
            signal_id,
            stocks=stock_repository.get_table_data(),
            daily_bars=daily_repository.get_table_data(),
            hot_stocks=stock_hot_repository.get_latest(),
            stock_daily_basic=stock_daily_basic_repository.get_latest_data(),
        )
    except Exception as error:
        logger.exception("执行信号 %s 失败", signal_id)
        raise HTTPException(
            status_code=500,
            detail=f"信号执行失败：{error}",
        ) from error

    return format_signal_result(signal_id, selected_stocks, limit=limit)


@router.get("/backtests/confirmed_volume_breakout")
async def confirmed_volume_breakout_backtest(
    stock_repository: StockListRepository,
    daily_repository: DailyRepository,
    stock_daily_basic_repository: StockDailyBasicRepo,
    stock_hot_repository: StockHotRepository,
    start_date: Annotated[
        date | None,
        Query(description="回测开始日期，默认按回看月数计算"),
    ] = None,
    end_date: Annotated[
        date | None,
        Query(description="回测结束日期，默认使用最新交易日"),
    ] = None,
    lookback_months: Annotated[int, Query(ge=1, le=60)] = 6,
    max_positions: Annotated[int, Query(ge=1, le=100)] = (
        BacktestConfig().max_positions
    ),
    initial_cash: Annotated[float, Query(gt=0)] = 1_000_000.0,
) -> dict[str, object]:
    """执行放量突破次日确认回测，返回绩效和逐笔交易记录。"""

    config = BacktestConfig(
        initial_cash=initial_cash,
        start_date=start_date,
        end_date=end_date,
        lookback_months=lookback_months,
        max_positions=max_positions,
    )

    def run_backtest():
        return ConfirmedVolumeBreakoutBacktest(config).run(
            stocks=stock_repository.get_table_data(),
            daily_bars=daily_repository.get_table_data(),
            hot_stocks=stock_hot_repository.get_table_data(),
            stock_daily_basic=stock_daily_basic_repository.get_table_data(),
        )

    try:
        result = await run_in_threadpool(run_backtest)
    except Exception as error:
        logger.exception("执行回测 confirmed_volume_breakout 失败")
        raise HTTPException(
            status_code=500,
            detail=f"策略回测失败：{error}",
        ) from error

    return format_backtest_result(
        result,
        strategy=find_signal("confirmed_volume_breakout"),
    )
