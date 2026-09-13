from __future__ import annotations
from contextlib import asynccontextmanager

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import router
from backend.app.config.config import get_settings
from backend.app.database import DuckDBDatabase, HKDuckDBDatabase, USDuckDBDatabase
from backend.app.jobs import create_scheduler
from backend.app.provider import HithinkProvider, IwencaiProvider, TushareProvider
from backend.app.repository import (
    DailyBarRepository,
    StockHotDailyRepository,
    StockDailyBasicRepository,
    StockRepository,
    HKDailyBarRepository,
    HKStockHotDailyRepository,
    HKStockRepository,
    USDailyBarRepository,
    USStockHotDailyRepository,
    USStockRepository,
)
from backend.app.services import CNMarketService, HKMarketService, USMarketService

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
    stock_repository = StockRepository(database)
    hk_stock_repository = HKStockRepository(hk_database)
    us_stock_repository = USStockRepository(us_database)
    stock_daily_basic_repository = StockDailyBasicRepository(database)
    daily_repository = DailyBarRepository(database)
    hk_daily_repository = HKDailyBarRepository(hk_database)
    us_daily_repository = USDailyBarRepository(us_database)
    stock_hot_repository = StockHotDailyRepository(database)
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
        stock_repository=stock_repository,
        stock_daily_basic_repository=stock_daily_basic_repository,
        daily_repository=daily_repository,
        iwencai_provider=iwencai_provider,
        stock_hot_repository=stock_hot_repository,
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
    app.state.stock_repository = stock_repository
    app.state.hk_stock_repository = hk_stock_repository
    app.state.us_stock_repository = us_stock_repository
    app.state.stock_daily_basic_repository = stock_daily_basic_repository
    app.state.daily_repository = daily_repository
    app.state.hk_daily_repository = hk_daily_repository
    app.state.us_daily_repository = us_daily_repository
    app.state.stock_hot_repository = stock_hot_repository
    app.state.hk_stock_hot_repository = hk_stock_hot_repository
    app.state.us_stock_hot_repository = us_stock_hot_repository
    app.state.cn_market_service = cn_market_service
    app.state.hk_market_service = hk_market_service
    app.state.us_market_service = us_market_service

    # 工作日按调度配置同步当日热门股数据。
    scheduler = create_scheduler(settings)
    app.state.scheduler = scheduler
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
