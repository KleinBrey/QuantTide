"""港股 ``hk_market.duckdb`` 数据仓库层。"""

from collections.abc import Iterable
from datetime import datetime

import pandas as pd

from ..database import HKDuckDBDatabase
from ..utils.symbol import normalize_daily_bar_symbol

HK_STOCK_COLUMNS = ["symbol", "name", "source"]

HK_DAILY_BAR_COLUMNS = [
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "source",
]

HK_STOCK_HOT_DAILY_COLUMNS = [
    "trade_date",
    "symbol",
    "name",
    "price",
    "change_pct",
    "hot_value",
    "source",
]


def _require_columns(rows: pd.DataFrame, required_columns: list[str]) -> None:
    missing_columns = [
        column for column in required_columns if column not in rows.columns
    ]
    if missing_columns:
        raise ValueError(f"入库数据缺少字段：{', '.join(missing_columns)}")


class BaseRepository:
    """保存港股 Repository 共用的数据库依赖。"""

    def __init__(self, db: HKDuckDBDatabase):
        self.db = db


class HKStockRepository(BaseRepository):
    """负责港股库 ``stocks`` 表的读写。"""

    def get_latest_update_time(self) -> datetime | None:
        with self.db.connection(read_only=True) as connection:
            row = connection.execute("SELECT MAX(update_time) FROM stocks").fetchone()
        return row[0] if row and row[0] is not None else None

    def get_table_data(self) -> pd.DataFrame:
        with self.db.connection(read_only=True) as connection:
            return connection.execute("SELECT * FROM stocks ORDER BY symbol").df()

    def upsert_stocks(self, rows: pd.DataFrame) -> int:
        if rows.empty:
            return 0

        stocks = rows.copy()
        if "source" not in stocks.columns:
            stocks["source"] = "Manual"
        _require_columns(stocks, HK_STOCK_COLUMNS)
        stocks = stocks[HK_STOCK_COLUMNS].copy()

        for column in HK_STOCK_COLUMNS:
            if stocks[column].isna().any():
                raise ValueError(f"股票池字段不能为空：{column}")
            stocks[column] = stocks[column].astype("string").str.strip()
            if stocks[column].eq("").any():
                raise ValueError(f"股票池字段不能为空：{column}")

        stocks["symbol"] = stocks["symbol"].str.upper()
        stocks = stocks.drop_duplicates(subset=["symbol"], keep="last")

        with self.db.connection() as connection:
            connection.register("incoming_hk_stocks", stocks)
            connection.execute("""
                INSERT INTO stocks (symbol, name, source)
                SELECT symbol, name, source
                FROM incoming_hk_stocks
                ON CONFLICT (symbol) DO UPDATE SET
                    name = excluded.name,
                    source = excluded.source,
                    update_time = now()
                """)
        return len(stocks)

    def delete_stocks(self, symbols: str | Iterable[str]) -> int:
        values = [symbols] if isinstance(symbols, str) else list(symbols)
        if any(symbol is None for symbol in values):
            raise ValueError("删除的股票代码不能为空")
        normalized = list(
            dict.fromkeys(str(symbol).strip().upper() for symbol in values)
        )
        if any(not symbol for symbol in normalized):
            raise ValueError("删除的股票代码不能为空")
        if not normalized:
            return 0

        deleting = pd.DataFrame({"symbol": normalized})
        with self.db.connection() as connection:
            connection.register("deleting_hk_stocks", deleting)
            affected_rows = connection.execute("""
                SELECT count(*)
                FROM stocks
                JOIN deleting_hk_stocks USING (symbol)
                """).fetchone()[0]
            connection.execute("""
                DELETE FROM stocks
                USING deleting_hk_stocks
                WHERE stocks.symbol = deleting_hk_stocks.symbol
                """)
        return affected_rows


class HKDailyBarRepository(BaseRepository):
    """负责港股库 ``daily_bars`` 表的读写。"""

    def get_latest_update_time(self) -> datetime | None:
        with self.db.connection(read_only=True) as connection:
            row = connection.execute(
                "SELECT MAX(update_time) FROM daily_bars"
            ).fetchone()
        return row[0] if row and row[0] is not None else None

    def get_table_data(self) -> pd.DataFrame:
        with self.db.connection(read_only=True) as connection:
            return connection.execute(
                "SELECT * FROM daily_bars ORDER BY symbol, trade_date"
            ).df()

    def get_by_symbol_and_date_range(
        self,
        symbol: object,
        start_date: object,
        end_date: object,
    ) -> pd.DataFrame:
        normalized_symbol = normalize_daily_bar_symbol(symbol, "hk-share")
        normalized_start = pd.to_datetime(start_date, errors="raise").date()
        normalized_end = pd.to_datetime(end_date, errors="raise").date()
        if normalized_start > normalized_end:
            raise ValueError("开始日期不能晚于结束日期")

        with self.db.connection(read_only=True) as connection:
            return connection.execute(
                """
                SELECT
                    symbol,
                    trade_date,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    amount,
                    source
                FROM daily_bars
                WHERE symbol = ?
                  AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                [normalized_symbol, normalized_start, normalized_end],
            ).df()

    def upsert_daily_bars(self, rows: pd.DataFrame) -> int:
        if rows.empty:
            return 0

        bars = rows.copy()
        if "amount" not in bars.columns:
            bars["amount"] = None
        _require_columns(bars, HK_DAILY_BAR_COLUMNS)
        bars = bars[HK_DAILY_BAR_COLUMNS]
        bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date

        with self.db.connection() as connection:
            connection.register("incoming_hk_daily_bars", bars)
            connection.execute("""
                INSERT INTO daily_bars (
                    symbol,
                    trade_date,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    amount,
                    source
                )
                SELECT
                    symbol,
                    trade_date,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    amount,
                    source
                FROM incoming_hk_daily_bars
                ON CONFLICT (symbol, trade_date) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    amount = excluded.amount,
                    source = excluded.source,
                    update_time = now()
                """)
        return len(bars)

    def insert_daily_bars(self, rows: pd.DataFrame) -> int:
        return self.upsert_daily_bars(rows)


class HKStockHotDailyRepository(BaseRepository):
    """负责港股库 ``stock_hot_daily`` 表的读写。"""

    def get_latest_update_time(self) -> datetime | None:
        with self.db.connection(read_only=True) as connection:
            row = connection.execute(
                "SELECT MAX(update_time) FROM stock_hot_daily"
            ).fetchone()
        return row[0] if row and row[0] is not None else None

    def get_latest(self) -> pd.DataFrame:
        with self.db.connection(read_only=True) as connection:
            return connection.execute("""
                SELECT
                    trade_date,
                    symbol,
                    name,
                    price,
                    change_pct,
                    hot_value,
                    source,
                    update_time
                FROM stock_hot_daily
                WHERE trade_date = (
                    SELECT MAX(trade_date) FROM stock_hot_daily
                )
                ORDER BY hot_value DESC, symbol
                """).df()

    def get_by_trade_date(self, trade_date: object) -> pd.DataFrame:
        normalized_date = pd.to_datetime(trade_date, errors="raise").date()
        with self.db.connection(read_only=True) as connection:
            return connection.execute(
                """
                SELECT
                    trade_date,
                    symbol,
                    name,
                    price,
                    change_pct,
                    hot_value,
                    source,
                    update_time
                FROM stock_hot_daily
                WHERE trade_date = ?
                ORDER BY hot_value DESC, symbol
                """,
                [normalized_date],
            ).df()

    def upsert_stock_hot_daily(self, rows: pd.DataFrame) -> int:
        if rows.empty:
            return 0

        hot_rows = rows.copy()
        if "source" not in hot_rows.columns:
            hot_rows["source"] = "Iwencai"
        _require_columns(hot_rows, HK_STOCK_HOT_DAILY_COLUMNS)
        hot_rows = hot_rows[HK_STOCK_HOT_DAILY_COLUMNS]
        hot_rows["trade_date"] = pd.to_datetime(
            hot_rows["trade_date"], errors="raise"
        ).dt.date
        hot_rows = hot_rows.drop_duplicates(
            subset=["trade_date", "symbol"], keep="last"
        )

        with self.db.connection() as connection:
            connection.register("incoming_stock_hot_daily", hot_rows)
            connection.execute("""
                INSERT INTO stock_hot_daily (
                    trade_date,
                    symbol,
                    name,
                    price,
                    change_pct,
                    hot_value,
                    source
                )
                SELECT
                    trade_date,
                    symbol,
                    name,
                    price,
                    change_pct,
                    hot_value,
                    source
                FROM incoming_stock_hot_daily
                ON CONFLICT (trade_date, symbol)
                DO UPDATE SET
                    name = excluded.name,
                    price = excluded.price,
                    change_pct = excluded.change_pct,
                    hot_value = excluded.hot_value,
                    source = excluded.source,
                    update_time = now()
                """)
        return len(hot_rows)

    def insert_stock_hot_daily(self, rows: pd.DataFrame) -> int:
        return self.upsert_stock_hot_daily(rows)
