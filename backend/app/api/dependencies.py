from fastapi import Request

from backend.app.repository import (
    DailyBarRepository,
    HKStockHotDailyRepository,
    StockHotDailyRepository,
    StockDailyBasicRepository,
    StockRepository,
    USStockHotDailyRepository,
)
from backend.app.services import Service


def get_stock_repository(request: Request) -> StockRepository:
    return request.app.state.stock_repository


def get_daily_repository(request: Request) -> DailyBarRepository:
    return request.app.state.daily_repository


def get_stock_daily_basic_repository(request: Request) -> StockDailyBasicRepository:
    return request.app.state.stock_daily_basic_repository


def get_stock_hot_repository(request: Request) -> StockHotDailyRepository:
    return request.app.state.stock_hot_repository


def get_hk_stock_hot_repository(request: Request) -> HKStockHotDailyRepository:
    return request.app.state.hk_stock_hot_repository


def get_us_stock_hot_repository(request: Request) -> USStockHotDailyRepository:
    return request.app.state.us_stock_hot_repository


def get_service(request: Request) -> Service:
    return request.app.state.service
