"""A 股 ``cn_market.duckdb`` 数据仓库层。

Repository 只负责数据库读写，不负责调用第三方接口或清洗业务数据。
每张表的冲突键和更新字段不同，因此由具体 Repository 明确实现写入逻辑。
"""

from datetime import datetime

import pandas as pd

from ..database import DuckDBDatabase
from ..utils.symbol import validate_symbol

STOCK_COLUMNS = ["symbol", "name", "exchange", "market", "source"]

STOCK_DAILY_BASIC_COLUMNS = ["symbol", "trade_date", "market_cap"]

DAILY_BAR_COLUMNS = [
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

STOCK_HOT_DAILY_COLUMNS = [
    "trade_date",
    "symbol",
    "name",
    "price",
    "change_pct",
    "rank",
    "source",
]


def _require_columns(rows: pd.DataFrame, required_columns: list[str]) -> None:
    """检查入库数据是否包含指定字段。"""

    missing_columns = [
        column for column in required_columns if column not in rows.columns
    ]
    if missing_columns:
        missing_text = ", ".join(missing_columns)
        raise ValueError(f"入库数据缺少字段：{missing_text}")


class BaseRepository:
    """保存具体 Repository 共用的数据库依赖。"""

    def __init__(self, db: DuckDBDatabase):
        self.db = db


class StockRepository(BaseRepository):
    """负责 stocks 表的读写。"""

    def get_latest_update_time(self) -> datetime | None:
        """获取股票基础信息表最近一次更新时间。"""

        with self.db.connection(read_only=True) as connection:
            row = connection.execute("SELECT MAX(update_time) FROM stocks").fetchone()

        return row[0] if row and row[0] is not None else None

    def get_table_data(self) -> pd.DataFrame:
        """获取全部股票基础信息。"""

        with self.db.connection(read_only=True) as connection:
            return connection.execute("SELECT * FROM stocks ORDER BY symbol").df()

    def upsert_stocks(self, rows: pd.DataFrame) -> int:
        """新增或更新股票基础信息，返回处理的行数。"""

        if rows.empty:
            return 0

        _require_columns(rows, STOCK_COLUMNS)
        stocks = rows[STOCK_COLUMNS].copy()

        with self.db.connection() as connection:
            connection.register("incoming_stocks", stocks)
            connection.execute("""
                INSERT INTO stocks (
                    symbol,
                    name,
                    exchange,
                    market,
                    source
                )
                SELECT
                    symbol,
                    name,
                    exchange,
                    market,
                    source
                FROM incoming_stocks
                ON CONFLICT (symbol) DO UPDATE SET
                    name = excluded.name,
                    exchange = excluded.exchange,
                    market = excluded.market,
                    source = excluded.source,
                    update_time = now()
                """)

        return len(stocks)

    def insert_stocks(self, rows: pd.DataFrame) -> int:
        """兼容原有调用；实际执行新增或更新。"""

        return self.upsert_stocks(rows)


class StockDailyBasicRepository(BaseRepository):
    """负责 stock_daily_basic 表的读写。"""

    def get_latest_update_time(self) -> datetime | None:
        """获取股票最新指标表最近一次更新时间。"""

        with self.db.connection(read_only=True) as connection:
            row = connection.execute(
                "SELECT MAX(update_time) FROM stock_daily_basic"
            ).fetchone()

        return row[0] if row and row[0] is not None else None

    def get_table_data(self) -> pd.DataFrame:
        """获取全部股票每日指标历史数据，供回测按日使用。"""
        with self.db.connection(read_only=True) as connection:
            return connection.execute("""
                SELECT *
                FROM stock_daily_basic
                ORDER BY trade_date, symbol
                """).df()

    def get_latest_data(self) -> pd.DataFrame:
        """获取每只股票最近交易日的每日指标快照。"""

        with self.db.connection(read_only=True) as connection:
            return connection.execute("""
                SELECT symbol, trade_date, market_cap, update_time
                FROM stock_daily_basic
                WHERE trade_date = (
                    SELECT MAX(trade_date) FROM stock_daily_basic
                )
                ORDER BY symbol
                """).df()

    def upsert_stock_daily_basic(self, rows: pd.DataFrame) -> int:
        """新增或更新股票每日指标，返回处理的行数。"""

        if rows.empty:
            return 0

        _require_columns(rows, STOCK_DAILY_BASIC_COLUMNS)
        daily_basic = (
            rows[STOCK_DAILY_BASIC_COLUMNS]
            .drop_duplicates(subset=["symbol", "trade_date"], keep="last")
            .copy()
        )
        with self.db.connection() as connection:
            connection.register("incoming_stock_daily_basic", daily_basic)
            connection.execute("""
                INSERT INTO stock_daily_basic (
                    symbol,
                    trade_date,
                    market_cap
                )
                SELECT
                    symbol,
                    trade_date,
                    market_cap
                FROM incoming_stock_daily_basic
                ON CONFLICT (symbol, trade_date) DO UPDATE SET
                    market_cap = excluded.market_cap,
                    update_time = now()
                """)

        return len(daily_basic)


class DailyBarRepository(BaseRepository):
    """负责 daily_bars 表的读写。"""

    def get_latest_update_time(self) -> datetime | None:
        """获取日 K 线表最近一次更新时间。"""

        with self.db.connection(read_only=True) as connection:
            row = connection.execute(
                "SELECT MAX(update_time) FROM daily_bars"
            ).fetchone()

        return row[0] if row and row[0] is not None else None

    def get_table_data(self) -> pd.DataFrame:
        """获取全部日线数据"""

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
        """查询一只股票在指定日期区间内的日 K 线。

        开始日期和结束日期都包含在查询范围内。股票代码会统一为项目内部
        使用的 6 位格式，因此 ``600519`` 和 ``600519.SH`` 查询结果相同。
        """

        normalized_symbol = validate_symbol(symbol)
        normalized_start = pd.to_datetime(start_date, errors="raise").date()
        normalized_end = pd.to_datetime(end_date, errors="raise").date()

        if normalized_start > normalized_end:
            raise ValueError("开始日期不能晚于结束日期")

        # 使用 SQL 参数而不是拼接字符串，避免特殊输入改变查询语义。
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
        """新增或更新日线数据，返回处理的行数。"""

        if rows.empty:
            return 0

        # amount 是表中的可选字段，数据源未提供时使用空值。
        bars = rows.copy()
        if "amount" not in bars.columns:
            bars["amount"] = None

        _require_columns(bars, DAILY_BAR_COLUMNS)
        bars = bars[DAILY_BAR_COLUMNS]

        # DuckDB 的目标字段是 DATE；无效日期会在这里明确报错。
        bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date

        with self.db.connection() as connection:
            connection.register("incoming_daily_bars", bars)
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
                FROM incoming_daily_bars
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
        """兼容 insert 风格命名；实际执行新增或更新。"""

        return self.upsert_daily_bars(rows)


class StockHotDailyRepository(BaseRepository):
    """负责 stock_hot_daily 表的读写。"""

    table_name = "stock_hot_daily"

    def get_latest_update_time(self) -> datetime | None:
        """获取股票热度表最近一次更新时间；无数据时返回 ``None``。"""

        with self.db.connection(read_only=True) as connection:
            row = connection.execute(
                f"SELECT MAX(update_time) FROM {self.table_name}"
            ).fetchone()

        return row[0] if row and row[0] is not None else None

    def get_latest(self) -> pd.DataFrame:
        """获取数据库中最新交易日的股票热度榜。"""

        with self.db.connection(read_only=True) as connection:
            return connection.execute(f"""
                SELECT
                    trade_date,
                    symbol,
                    name,
                    price,
                    change_pct,
                    rank,
                    source,
                    update_time
                FROM {self.table_name}
                WHERE trade_date = (
                    SELECT MAX(trade_date) FROM {self.table_name}
                )
                ORDER BY rank ASC, symbol
                """).df()

    def get_table_data(self) -> pd.DataFrame:
        """获取全部历史股票热度，供回测按日使用。"""

        with self.db.connection(read_only=True) as connection:
            return connection.execute(f"""
                SELECT
                    trade_date,
                    symbol,
                    name,
                    price,
                    change_pct,
                    rank,
                    source,
                    update_time
                FROM {self.table_name}
                ORDER BY trade_date, rank ASC, symbol
                """).df()

    def get_by_trade_date(self, trade_date: object) -> pd.DataFrame:
        """按交易日获取股票热度列表，并按排名从小到大排列。"""

        normalized_date = pd.to_datetime(trade_date, errors="raise").date()

        with self.db.connection(read_only=True) as connection:
            return connection.execute(
                f"""
                SELECT
                    trade_date,
                    symbol,
                    name,
                    price,
                    change_pct,
                    rank,
                    source,
                    update_time
                FROM {self.table_name}
                WHERE trade_date = ?
                ORDER BY rank ASC, symbol
                """,
                [normalized_date],
            ).df()

    def upsert_stock_hot_daily(self, rows: pd.DataFrame) -> int:
        """用完整的新榜单替换对应交易日的旧榜单，失败则回滚。"""

        if rows.empty:
            return 0

        hot_rows = rows.copy()
        if "source" not in hot_rows.columns:
            hot_rows["source"] = "Iwencai"
        _require_columns(hot_rows, STOCK_HOT_DAILY_COLUMNS)
        hot_rows = hot_rows[STOCK_HOT_DAILY_COLUMNS]
        hot_rows["trade_date"] = pd.to_datetime(
            hot_rows["trade_date"], errors="raise"
        ).dt.date
        # 现有数据库可能还没有排名唯一约束，写入前检查一次。
        if hot_rows.duplicated(["trade_date", "rank"]).any():
            raise ValueError("同一交易日的排名不能重复")

        with self.db.connection() as connection:
            connection.register("incoming_stock_hot_daily", hot_rows)
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.execute("""
                    DELETE FROM stock_hot_daily
                    WHERE trade_date IN (
                        SELECT DISTINCT trade_date FROM incoming_stock_hot_daily
                    )
                """)
                connection.execute("""
                    INSERT INTO stock_hot_daily (
                        trade_date, symbol, name, price, change_pct, rank, source
                    )
                    SELECT trade_date, symbol, name, price, change_pct, rank, source
                    FROM incoming_stock_hot_daily
                """)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

        return len(hot_rows)

    def insert_stock_hot_daily(self, rows: pd.DataFrame) -> int:
        """兼容 insert 风格命名；实际按交易日整批替换。"""

        return self.upsert_stock_hot_daily(rows)

    def fill_stock_hot_daily(self, rows: pd.DataFrame) -> int:
        """写入历史排名，覆盖同日同股票或同日同排名的旧记录。"""
        if rows.empty:
            return 0

        hot_rows = rows[STOCK_HOT_DAILY_COLUMNS].copy()
        hot_rows["trade_date"] = pd.to_datetime(hot_rows["trade_date"]).dt.date
        with self.db.connection() as connection:
            connection.register("incoming_hot_history", hot_rows)
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.execute("""
                    DELETE FROM stock_hot_daily existing
                    USING incoming_hot_history incoming
                    WHERE existing.trade_date = incoming.trade_date
                      AND (existing.symbol = incoming.symbol
                           OR existing.rank = incoming.rank)
                """)
                connection.execute("""
                    INSERT INTO stock_hot_daily (
                        trade_date, symbol, name, price, change_pct, rank, source
                    )
                    SELECT trade_date, symbol, name, price, change_pct, rank, source
                    FROM incoming_hot_history
                """)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return len(hot_rows)
