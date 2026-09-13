"""
Repository 层：数据访问对象（DAO）。
负责所有数据库操作的封装。
"""

from .cn_market_db import (
    BaseRepository,
    DailyBarRepository,
    StockHotDailyRepository,
    StockDailyBasicRepository,
    StockRepository,
)

from .hk_market_db import (
    HKDailyBarRepository,
    HKStockHotDailyRepository,
    HKStockRepository,
)

from .us_market_db import (
    USDailyBarRepository,
    USStockHotDailyRepository,
    USStockRepository,
)

__all__ = [
    "BaseRepository",
    "StockRepository",
    "StockDailyBasicRepository",
    "DailyBarRepository",
    "StockHotDailyRepository",
    "HKStockRepository",
    "HKDailyBarRepository",
    "HKStockHotDailyRepository",
    "USStockRepository",
    "USDailyBarRepository",
    "USStockHotDailyRepository",
]
