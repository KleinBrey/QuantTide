from datetime import date, datetime

from pydantic import BaseModel


class Stock(BaseModel):
    symbol: str
    name: str
    exchange: str
    market: str
    source: str
    update_time: datetime


class GlobalStock(BaseModel):
    """港股和美股股票池中的一条记录。"""

    symbol: str
    name: str
    source: str
    update_time: datetime


class DailyBar(BaseModel):
    """一只股票单个交易日的日 K 线。"""

    symbol: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None = None
    source: str


class HotStock(BaseModel):
    """股票热度榜中的一条记录。"""

    trade_date: date
    symbol: str
    name: str
    price: float | None = None
    change_pct: float | None = None
    hot_value: float
    source: str
    update_time: datetime
