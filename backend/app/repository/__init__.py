"""
Repository 层：数据访问对象（DAO）。
负责所有数据库操作的封装。
"""

from .duck_db import (
    BaseRepository,
    DailyBarRepository,
    HKStockHotDailyRepository,
    StockHotDailyRepository,
    StockDailyBasicRepository,
    StockRepository,
    USStockHotDailyRepository,
)

__all__ = [
    "BaseRepository",
    "StockRepository",
    "StockDailyBasicRepository",
    "DailyBarRepository",
    "StockHotDailyRepository",
    "HKStockHotDailyRepository",
    "USStockHotDailyRepository",
]
