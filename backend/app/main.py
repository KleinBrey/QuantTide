from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api import router
from backend.app.config.config import get_settings
from backend.app.database import DuckDBDatabase, HKDuckDBDatabase, USDuckDBDatabase, SQLiteDatabase
from backend.app.jobs import create_scheduler
from backend.app.provider import HithinkProvider, IwencaiProvider, TushareProvider
from backend.app.repository import (
    DailyBarRepository,
    DailyHotRepository,
    DailyBasicRepository,
    DailyStockRepository,
    HKDailyBarRepository,
    HKStockHotDailyRepository,
    HKStockRepository,
    USDailyBarRepository,
    USStockHotDailyRepository,
    USStockRepository,
)
from backend.app.repository.task import TaskRepository
from backend.app.repository.watchlist import WatchlistRepository, WatchlistError
from backend.app.services import CNMarketService, HKMarketService, USMarketService
from backend.app.services.task_service import TaskService
from backend.app.services.watchlist_service import WatchlistService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):

    settings = get_settings()

    # A 股、港股和美股分别使用独立的数据库文件。
    database = DuckDBDatabase(settings.database_path)
    hk_database = HKDuckDBDatabase(settings.hk_database_path)
    us_database = USDuckDBDatabase(settings.us_database_path)
    database.initialize()
    hk_database.initialize()
    us_database.initialize()

    # 注册stock表的repository，用来统一处理增删改查
    daily_stock_repository = DailyStockRepository(database)
    hk_stock_repository = HKStockRepository(hk_database)
    us_stock_repository = USStockRepository(us_database)
    app_database = SQLiteDatabase(settings.app_database_path)
    app_database.initialize()
    watchlist_repository = WatchlistRepository(app_database)
    # 启动时只确保默认分组存在；股票由用户在页面上添加，不预填名单。
    watchlist_repository.ensure_default_pool('HK')
    watchlist_repository.ensure_default_pool('US')
    app.state.watchlist_service = WatchlistService(
        watchlist_repository, daily_stock_repository, hk_stock_repository, us_stock_repository,
    )
    daily_basic_repository = DailyBasicRepository(database)
    daily_repository = DailyBarRepository(database)
    hk_daily_repository = HKDailyBarRepository(hk_database)
    us_daily_repository = USDailyBarRepository(us_database)
    daily_hot_repository = DailyHotRepository(database)
    hk_stock_hot_repository = HKStockHotDailyRepository(hk_database)
    us_stock_hot_repository = USStockHotDailyRepository(us_database)

    # 注册API调用
    hithink_provider = HithinkProvider()
    tushare_provider = TushareProvider()
    iwencai_provider = IwencaiProvider()

    # 业务逻辑处理
    cn_market_service = CNMarketService(
        hithink_provider=hithink_provider,
        tushare_provider=tushare_provider,
        daily_stock_repository=daily_stock_repository,
        daily_basic_repository=daily_basic_repository,
        daily_repository=daily_repository,
        iwencai_provider=iwencai_provider,
        daily_hot_repository=daily_hot_repository,
    )
    hk_market_service = HKMarketService(
        iwencai_provider=iwencai_provider,
        stock_hot_repository=hk_stock_hot_repository,
    )
    us_market_service = USMarketService(
        iwencai_provider=iwencai_provider,
        stock_hot_repository=us_stock_hot_repository,
    )

    # 将共享实例挂载到 app.state，供路由及其他应用组件复用。
    app.state.daily_stock_repository = daily_stock_repository
    app.state.hk_stock_repository = hk_stock_repository
    app.state.us_stock_repository = us_stock_repository
    app.state.daily_basic_repository = daily_basic_repository
    app.state.daily_repository = daily_repository
    app.state.hk_daily_repository = hk_daily_repository
    app.state.us_daily_repository = us_daily_repository
    app.state.daily_hot_repository = daily_hot_repository
    app.state.hk_stock_hot_repository = hk_stock_hot_repository
    app.state.us_stock_hot_repository = us_stock_hot_repository
    app.state.cn_market_service = cn_market_service
    app.state.hk_market_service = hk_market_service
    app.state.us_market_service = us_market_service

    # 任务由用户在前端添加，启动时只读取已有配置。
    task_repository = TaskRepository(app_database)

    # 1. 创建 Scheduler，此时不会执行任何任务。
    scheduler = create_scheduler(settings)
    # 2. 创建 TaskService，交给它数据库和调度器。
    task_service = TaskService(
        repository=task_repository,
        scheduler=scheduler,
        settings=settings,
    )
    app.state.task_service = task_service
    app.state.scheduler = scheduler

    # 3. 从 SQLite 加载任务，登记到 Scheduler。
    task_service.load_scheduled_tasks()
    # 4. 启动 Scheduler；关闭自动调度时仍可管理、手动执行任务。
    if settings.scheduler_enabled:
        scheduler.start()

    # yield 之前的代码会在应用启动时执行。
    # 执行到 yield 后，FastAPI 开始正常接收和处理请求。
    # 当应用关闭时，程序会从 yield 后面继续执行清理代码。
    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)


@app.exception_handler(WatchlistError)
async def watchlist_error_handler(request, error: WatchlistError):
    return JSONResponse(status_code=error.status_code, content={'detail': str(error)})

# 允许配置中声明的前端来源跨域访问 API。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)


@app.get("/")
def root() -> dict[str, str]:
    """返回服务基本信息和交互式 API 文档入口。"""
    return {"name": settings.app_name, "docs": "/docs"}
