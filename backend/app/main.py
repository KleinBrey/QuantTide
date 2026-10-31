from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api import router
from backend.app.config.config import get_settings
from backend.app.database import (
    CryptoDuckDBDatabase,
    DuckDBDatabase,
    FuturesDuckDBDatabase,
    HKDuckDBDatabase,
    SQLiteDatabase,
    USDuckDBDatabase,
)
from backend.app.jobs import create_scheduler
from backend.app.provider import (
    BinanceProvider,
    HithinkProvider,
    IwencaiProvider,
    TushareProvider,
    YFinanceProvider,
)
from backend.app.repository import (
    DailyBarRepository,
    DailyBasicRepository,
    DailyHotRepository,
    DailyStockRepository,
    HKDailyBarRepository,
    HKStockHotDailyRepository,
    HKStockRepository,
    USDailyBarRepository,
    USStockHotDailyRepository,
    USStockRepository,
)
from backend.app.repository.crypto_market_db import CryptoMarketRepository
from backend.app.repository.futures_market_db import FuturesMarketRepository
from backend.app.repository.task import TaskRepository
from backend.app.repository.watchlist import WatchlistError, WatchlistRepository
from backend.app.services import CNMarketService, HKMarketService, USMarketService
from backend.app.services.crypto_market_service import CryptoMarketService
from backend.app.services.task_service import TaskService
from backend.app.services.watchlist_service import WatchlistService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时组装共享依赖和调度器，关闭时停止调度器。"""
    settings = get_settings()

    # 初始化数据库：各市场行情独立存储，自选分组和任务共用 SQLite。
    database = DuckDBDatabase(settings.database_path)
    hk_database = HKDuckDBDatabase(settings.hk_database_path)
    us_database = USDuckDBDatabase(settings.us_database_path)
    crypto_database = CryptoDuckDBDatabase(settings.crypto_database_path)
    futures_database = FuturesDuckDBDatabase(settings.futures_database_path)
    app_database = SQLiteDatabase(settings.app_database_path)

    database.initialize()
    hk_database.initialize()
    us_database.initialize()
    crypto_database.initialize()
    futures_database.initialize()
    app_database.initialize()

    # 创建数据仓库，按 A 股、港股、美股、加密货币、期货和应用配置归组。
    daily_stock_repository = DailyStockRepository(database)
    daily_basic_repository = DailyBasicRepository(database)
    daily_repository = DailyBarRepository(database)
    daily_hot_repository = DailyHotRepository(database)

    hk_stock_repository = HKStockRepository(hk_database)
    hk_daily_repository = HKDailyBarRepository(hk_database)
    hk_stock_hot_repository = HKStockHotDailyRepository(hk_database)

    us_stock_repository = USStockRepository(us_database)
    us_daily_repository = USDailyBarRepository(us_database)
    us_stock_hot_repository = USStockHotDailyRepository(us_database)

    crypto_repository = CryptoMarketRepository(crypto_database)
    futures_repository = FuturesMarketRepository(futures_database)

    watchlist_repository = WatchlistRepository(app_database)
    task_repository = TaskRepository(app_database)

    # 启动时只确保默认分组存在；股票和交易对由用户在页面上添加。
    for market in ("HK", "US", "CRYPTO", "FUTURES"):
        watchlist_repository.ensure_default_pool(market)

    # 创建行情数据提供方。
    hithink_provider = HithinkProvider()
    tushare_provider = TushareProvider()
    iwencai_provider = IwencaiProvider()
    yfinance_provider = YFinanceProvider()
    binance_provider = BinanceProvider()

    # 组装市场、自选分组和任务服务。
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
        yfinance_provider=yfinance_provider,
        daily_repository=hk_daily_repository,
        watchlist_repository=watchlist_repository,
    )
    us_market_service = USMarketService(
        iwencai_provider=iwencai_provider,
        stock_hot_repository=us_stock_hot_repository,
        yfinance_provider=yfinance_provider,
        daily_repository=us_daily_repository,
        watchlist_repository=watchlist_repository,
    )
    crypto_market_service = CryptoMarketService(
        provider=binance_provider,
        repository=crypto_repository,
    )
    watchlist_service = WatchlistService(
        repository=watchlist_repository,
        cn_repository=daily_stock_repository,
        hk_repository=hk_stock_repository,
        us_repository=us_stock_repository,
        crypto_repository=crypto_repository,
        futures_repository=futures_repository,
    )
    scheduler = create_scheduler(settings)
    task_service = TaskService(
        repository=task_repository,
        scheduler=scheduler,
        settings=settings,
    )

    # 将共享实例挂载到 app.state，供路由及其他应用组件复用。
    app.state.daily_stock_repository = daily_stock_repository
    app.state.daily_basic_repository = daily_basic_repository
    app.state.daily_repository = daily_repository
    app.state.daily_hot_repository = daily_hot_repository

    app.state.hk_stock_repository = hk_stock_repository
    app.state.hk_daily_repository = hk_daily_repository
    app.state.hk_stock_hot_repository = hk_stock_hot_repository

    app.state.us_stock_repository = us_stock_repository
    app.state.us_daily_repository = us_daily_repository
    app.state.us_stock_hot_repository = us_stock_hot_repository
    app.state.futures_repository = futures_repository

    app.state.cn_market_service = cn_market_service
    app.state.hk_market_service = hk_market_service
    app.state.us_market_service = us_market_service
    app.state.crypto_market_service = crypto_market_service
    app.state.watchlist_service = watchlist_service
    app.state.task_service = task_service
    app.state.scheduler = scheduler

    # 任务由用户在前端添加；启动时只加载已有任务，并按配置开启自动调度。
    task_service.load_scheduled_tasks()
    if settings.scheduler_enabled:
        scheduler.start()

    # 应用运行期间处理请求，关闭时清理调度器。
    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)


@app.exception_handler(WatchlistError)
async def watchlist_error_handler(request, error: WatchlistError):
    return JSONResponse(status_code=error.status_code, content={"detail": str(error)})


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
