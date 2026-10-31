"""期货资料和日线的数据库读写。"""

from datetime import datetime

MAIN_CONTRACT_FILTER = """main_symbol IS NOT NULL AND trim(main_symbol) <> ''
    AND main_name IS NOT NULL AND trim(main_name) <> ''"""


class FuturesMarketRepository:
    def __init__(self, db):
        self.db = db

    def get_latest_update_time(self) -> datetime | None:
        with self.db.connection(read_only=True) as connection:
            row = connection.execute(
                "SELECT MAX(update_time) FROM daily_bars"
            ).fetchone()
        return row[0] if row and row[0] is not None else None

    def list_contract_symbols(self):
        with self.db.connection(read_only=True) as connection:
            return [row[0] for row in connection.execute(
                f"SELECT symbol FROM contracts WHERE {MAIN_CONTRACT_FILTER} ORDER BY symbol"
            ).fetchall()]

    def upsert_contracts(self, rows, *, replace=False):
        if rows.empty:
            return 0
        rows = rows.copy()
        for column in ("main_symbol", "main_name", "trade_date"):
            if column not in rows:
                rows[column] = None
        with self.db.connection() as connection:
            connection.register("incoming", rows)
            connection.begin()
            connection.execute("""
                INSERT INTO contracts (symbol, name, exchange, code,
                    main_symbol, main_name, trade_date)
                SELECT symbol, name, exchange, code,
                    main_symbol, main_name, trade_date FROM incoming
                ON CONFLICT (symbol) DO UPDATE SET name = excluded.name,
                    exchange = excluded.exchange, code = excluded.code,
                    main_symbol = excluded.main_symbol,
                    main_name = excluded.main_name,
                    trade_date = excluded.trade_date,
                    update_time = now()
            """)
            if replace:
                connection.execute("DELETE FROM contracts WHERE symbol NOT IN (SELECT symbol FROM incoming)")
            connection.commit()
        return len(rows)

    def upsert_daily_bars(self, rows):
        if rows.empty:
            return 0
        with self.db.connection() as connection:
            connection.register("incoming", rows)
            connection.execute("""
                INSERT INTO daily_bars
                    (symbol, trade_date, open, high, low, close, volume, amount, settle, open_interest)
                SELECT symbol, trade_date, open, high, low, close, volume, amount, settle, open_interest
                FROM incoming
                ON CONFLICT (symbol, trade_date) DO UPDATE SET
                    open = excluded.open, high = excluded.high, low = excluded.low,
                    close = excluded.close, volume = excluded.volume, amount = excluded.amount,
                    settle = excluded.settle, open_interest = excluded.open_interest,
                    update_time = now()
            """)
        return len(rows)

    def get_by_symbol_and_date_range(self, symbol, start_date, end_date):
        with self.db.connection(read_only=True) as connection:
            return connection.execute("""
                SELECT symbol, trade_date, open, high, low, close, volume, amount, source
                FROM daily_bars WHERE symbol = ? AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date
            """, [symbol, start_date, end_date]).df()
