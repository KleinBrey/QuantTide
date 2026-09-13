"""各市场共用的股票热度同步与缓存逻辑。"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from ..provider import IwencaiProvider


class _HotStockRepository(Protocol):
    """热度服务依赖的最小 Repository 接口。"""

    def get_latest_update_time(self) -> datetime | None: ...

    def upsert_stock_hot_daily(self, rows: pd.DataFrame) -> int: ...

    def get_latest(self) -> pd.DataFrame: ...


class HotStockService:
    """封装不同市场共用的问财热度同步与缓存流程。"""

    HOT_STOCK_CACHE_TTL = timedelta(hours=2)

    def __init__(
        self,
        *,
        iwencai_provider: IwencaiProvider | None,
        stock_hot_repository: _HotStockRepository | None,
        fetch_method_name: str,
        market_name: str,
    ) -> None:
        self.iwencai_provider = iwencai_provider
        self.stock_hot_repository = stock_hot_repository
        self._fetch_method_name = fetch_method_name
        self._market_name = market_name
        self._hot_stock_sync_lock = threading.Lock()

    @staticmethod
    def format_hot_stock(
        value: pd.DataFrame,
        trade_date: date | datetime | str,
    ) -> pd.DataFrame:
        """把问财热度结果格式化为热度表结构。"""

        columns = [
            "trade_date",
            "symbol",
            "name",
            "price",
            "change_pct",
            "hot_value",
            "source",
        ]
        frame = pd.DataFrame(value).copy()
        if frame.empty:
            return pd.DataFrame(columns=columns)

        if "hot_value" not in frame.columns and "hot_rank" in frame.columns:
            frame = frame.rename(columns={"hot_rank": "hot_value"})

        required_columns = ["symbol", "name", "price", "change_pct", "hot_value"]
        missing_columns = [
            column for column in required_columns if column not in frame.columns
        ]
        if missing_columns:
            raise ValueError(f"股票热度数据缺少字段：{', '.join(missing_columns)}")

        frame["trade_date"] = pd.to_datetime(trade_date, errors="raise").date()
        frame["name"] = frame["name"].astype("string").str.strip()
        for column in ["price", "change_pct", "hot_value"]:
            frame[column] = pd.to_numeric(
                frame[column].astype("string").str.rstrip("%"), errors="coerce"
            )
        frame["source"] = "Iwencai"

        frame = frame.dropna(subset=["symbol", "name", "hot_value"])
        frame = frame.drop_duplicates(subset=["trade_date", "symbol"], keep="last")
        return frame[columns].reset_index(drop=True)

    def update_hot_stock(
        self,
        trade_date: date | datetime | str | None = None,
    ) -> int:
        """获取并保存当前市场指定交易日的问财股票热度榜。"""

        if self.iwencai_provider is None or self.stock_hot_repository is None:
            raise RuntimeError("未配置问财 Provider 或股票热度 Repository")

        if trade_date is None:
            trade_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()

        try:
            result = getattr(self.iwencai_provider, self._fetch_method_name)()
            hot_rows = self.format_hot_stock(result, trade_date)
            affected_rows = self.stock_hot_repository.upsert_stock_hot_daily(hot_rows)
        except Exception as error:
            print(f"{self._market_name}热度更新失败: {error}")
            raise

        print(f"{self._market_name}热度更新成功，共写入 {affected_rows} 条")
        return affected_rows

    def get_hot_stock(
        self,
        request_time: datetime | None = None,
    ) -> pd.DataFrame:
        """返回当前市场最新热度榜，缓存超过两小时时先同步。"""

        if self.stock_hot_repository is None:
            raise RuntimeError("未配置股票热度 Repository")

        current_time = request_time or datetime.now(ZoneInfo("Asia/Shanghai"))
        latest_update_time = self.stock_hot_repository.get_latest_update_time()

        if not self._is_hot_stock_fresh(latest_update_time, current_time):
            with self._hot_stock_sync_lock:
                latest_update_time = self.stock_hot_repository.get_latest_update_time()
                if not self._is_hot_stock_fresh(latest_update_time, current_time):
                    trade_date = self._to_shanghai_naive(current_time).date()
                    self.update_hot_stock(trade_date)

        return self.stock_hot_repository.get_latest()

    def _is_hot_stock_fresh(
        self,
        latest_update_time: datetime | None,
        request_time: datetime,
    ) -> bool:
        """判断热度数据距请求时间是否严格不足两小时。"""

        if latest_update_time is None:
            return False

        latest = self._to_shanghai_naive(latest_update_time)
        requested_at = self._to_shanghai_naive(request_time)
        return requested_at - latest < self.HOT_STOCK_CACHE_TTL

    @staticmethod
    def _to_shanghai_naive(value: datetime) -> datetime:
        """将时间统一为上海时区的无时区时间，兼容 DuckDB TIMESTAMP。"""

        if value.tzinfo is None:
            return value
        return value.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
