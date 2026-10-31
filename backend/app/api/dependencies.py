from typing import Annotated

from fastapi import Depends, Request

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
from backend.app.services import CNMarketService, HKMarketService, USMarketService
from backend.app.repository.crypto_market_db import CryptoMarketRepository
from backend.app.services.crypto_market_service import CryptoMarketService
from backend.app.services.task_service import TaskService
from backend.app.services.watchlist_service import WatchlistService


def get_futures_repository(request: Request):
    return request.app.state.futures_repository


def get_crypto_repository(request: Request) -> CryptoMarketRepository:
    return request.app.state.crypto_repository


def get_task_service(request: Request) -> TaskService:
    return request.app.state.task_service


def get_watchlist_service(request: Request) -> WatchlistService:
    return request.app.state.watchlist_service


def get_daily_stock_repository(request: Request) -> DailyStockRepository:
    return request.app.state.daily_stock_repository


def get_hk_stock_repository(request: Request) -> HKStockRepository:
    return request.app.state.hk_stock_repository


def get_us_stock_repository(request: Request) -> USStockRepository:
    return request.app.state.us_stock_repository


def get_daily_repository(request: Request) -> DailyBarRepository:
    return request.app.state.daily_repository


def get_hk_daily_repository(request: Request) -> HKDailyBarRepository:
    return request.app.state.hk_daily_repository


def get_us_daily_repository(request: Request) -> USDailyBarRepository:
    return request.app.state.us_daily_repository


def get_daily_basic_repository(request: Request) -> DailyBasicRepository:
    return request.app.state.daily_basic_repository


def get_daily_hot_repository(request: Request) -> DailyHotRepository:
    return request.app.state.daily_hot_repository


def get_hk_stock_hot_repository(request: Request) -> HKStockHotDailyRepository:
    return request.app.state.hk_stock_hot_repository


def get_us_stock_hot_repository(request: Request) -> USStockHotDailyRepository:
    return request.app.state.us_stock_hot_repository


def get_cn_market_service(request: Request) -> CNMarketService:
    return request.app.state.cn_market_service


def get_hk_market_service(request: Request) -> HKMarketService:
    return request.app.state.hk_market_service


def get_us_market_service(request: Request) -> USMarketService:
    return request.app.state.us_market_service


def get_crypto_market_service(request: Request) -> CryptoMarketService:
    return request.app.state.crypto_market_service


# 使用 Annotated 封装依赖声明，避免每个接口重复书写 Depends。
FuturesRepository = Annotated[object, Depends(get_futures_repository)]
CryptoRepository = Annotated[CryptoMarketRepository, Depends(get_crypto_repository)]
DailyStockRepo = Annotated[DailyStockRepository, Depends(get_daily_stock_repository)]
HKStockListRepository = Annotated[HKStockRepository, Depends(get_hk_stock_repository)]
USStockListRepository = Annotated[USStockRepository, Depends(get_us_stock_repository)]
DailyRepository = Annotated[DailyBarRepository, Depends(get_daily_repository)]
HKDailyRepository = Annotated[HKDailyBarRepository, Depends(get_hk_daily_repository)]
USDailyRepository = Annotated[USDailyBarRepository, Depends(get_us_daily_repository)]
DailyBasicRepo = Annotated[DailyBasicRepository, Depends(get_daily_basic_repository)]
DailyHotRepo = Annotated[DailyHotRepository, Depends(get_daily_hot_repository)]
HKStockHotRepository = Annotated[
    HKStockHotDailyRepository,
    Depends(get_hk_stock_hot_repository),
]
USStockHotRepository = Annotated[
    USStockHotDailyRepository,
    Depends(get_us_stock_hot_repository),
]
CNMarketServiceDep = Annotated[CNMarketService, Depends(get_cn_market_service)]
HKMarketServiceDep = Annotated[HKMarketService, Depends(get_hk_market_service)]
USMarketServiceDep = Annotated[USMarketService, Depends(get_us_market_service)]
CryptoMarketServiceDep = Annotated[CryptoMarketService, Depends(get_crypto_market_service)]

WatchlistServiceDep = Annotated[WatchlistService, Depends(get_watchlist_service)]
