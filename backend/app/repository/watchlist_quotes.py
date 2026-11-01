"""批量读取单个市场中自选股的最新已保存行情。"""

import pandas as pd


def latest_watchlist_quotes(database, symbols):
    if not symbols:
        return []
    placeholders = ",".join("?" for _ in symbols)
    with database.connection(read_only=True) as connection:
        rows = connection.execute(
            f"""
            WITH quotes AS (
                SELECT symbol, trade_date AS quote_date, close AS price,
                       lag(close) OVER (PARTITION BY symbol ORDER BY trade_date) AS previous_close,
                       row_number() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS position
                FROM daily_bars WHERE symbol IN ({placeholders})
            )
            SELECT symbol, quote_date, price,
                   CASE WHEN previous_close > 0
                        THEN (price / previous_close - 1) * 100
                   END AS change_pct
            FROM quotes WHERE position = 1
            """,
            symbols,
        ).df()
    return rows.astype(object).where(pd.notna(rows), None).to_dict(orient="records")
