from fastapi import Request

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
from backend.app.services import CNMarketService, HKMarketService, USMarketService


def get_stock_repository(request: Request) -> StockRepository:
    return request.app.state.stock_repository


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


def get_stock_daily_basic_repository(request: Request) -> StockDailyBasicRepository:
    return request.app.state.stock_daily_basic_repository


def get_stock_hot_repository(request: Request) -> StockHotDailyRepository:
    return request.app.state.stock_hot_repository


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
