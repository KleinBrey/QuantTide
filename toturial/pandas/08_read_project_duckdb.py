"""Pandas 第 8 课：从项目的 DuckDB 读取真实数据，并转成 DataFrame。"""

from pathlib import Path

import duckdb


project_root = Path(__file__).resolve().parents[2]
database_path = project_root / "data" / "cn_market.duckdb"
symbols = ["600519", "000001", "300750"]

if not database_path.exists():
    raise FileNotFoundError(f"数据库不存在：{database_path}")

# read_only=True 很重要：教程只读数据，不会误改项目数据库。
connection = duckdb.connect(str(database_path), read_only=True)
try:
    stocks = connection.execute(
        """
        SELECT symbol, name, exchange, market
        FROM stocks
        WHERE symbol IN (?, ?, ?)
        ORDER BY symbol
        """,
        symbols,
    ).df()

    bars = connection.execute(
        """
        SELECT symbol, date, open, high, low, close, volume, amount
        FROM daily_bars
        WHERE symbol IN (?, ?, ?)
        ORDER BY symbol, date
        """,
        symbols,
    ).df()
finally:
    connection.close()

print("=== 股票信息 ===")
print(stocks.to_string(index=False))
print(f"\n读取到 {len(bars)} 条日 K")
print("日期范围：", bars["date"].min(), "至", bars["date"].max())

# 数据从 DuckDB 进入 DataFrame 后，后续操作和读取 CSV 完全相同。
latest = bars.groupby("symbol", as_index=False).tail(1)
latest = latest.merge(stocks, on="symbol", how="left", validate="many_to_one")

print("\n=== 每只股票的最新行情 ===")
print(latest[["symbol", "name", "date", "close", "volume"]].to_string(index=False))
