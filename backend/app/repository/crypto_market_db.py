"""加密货币行情的数据库读写。"""

from datetime import datetime

import pandas as pd

from ..database import CryptoDuckDBDatabase


class CryptoMarketRepository:
    def __init__(self, db: CryptoDuckDBDatabase):
        self.db = db

    def get_latest_update_time(self) -> datetime | None:
        with self.db.connection(read_only=True) as connection:
            row = connection.execute("SELECT MAX(update_time) FROM daily_bars").fetchone()
        return row[0] if row and row[0] is not None else None

    def list_symbols(self) -> list[dict]:
        # 列表直接取已保存行情的交易对，无需再维护一份重复名单。
        with self.db.connection() as connection:
            return connection.execute("""
                SELECT symbol, max(trade_date) AS latest_date,
                       max(update_time) AS update_time
                FROM daily_bars GROUP BY symbol ORDER BY symbol
            """).df().to_dict(orient="records")

    def get_daily_bars(self, symbol: str) -> list[dict]:
        with self.db.connection() as connection:
            return connection.execute("""
                SELECT symbol, trade_date, open, high, low, close, volume, amount, source
                FROM daily_bars WHERE symbol = ? ORDER BY trade_date
            """, [symbol]).df().to_dict(orient="records")

    def upsert_daily_bars(self, rows: pd.DataFrame) -> int:
        if rows.empty:
            return 0
        with self.db.connection() as connection:
            connection.register("incoming_crypto_bars", rows)
            connection.execute("""
                INSERT INTO daily_bars
                    (symbol, trade_date, open, high, low, close, volume, amount, source)
                SELECT symbol, trade_date, open, high, low, close, volume, amount, source
                FROM incoming_crypto_bars
                ON CONFLICT (symbol, trade_date) DO UPDATE SET
                    open = excluded.open, high = excluded.high,
                    low = excluded.low, close = excluded.close,
                    volume = excluded.volume, amount = excluded.amount,
                    source = excluded.source, update_time = now()
            """)
        return len(rows)
