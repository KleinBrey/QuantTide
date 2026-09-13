"""Pandas 第 9 课：把读取、计算和汇总组成一个小型分析流程。"""

from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "data" / "cn_market.duckdb"
SYMBOLS = ["600519", "000001", "300750"]


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """从项目数据库读取三只示例股票。"""

    connection = duckdb.connect(str(DATABASE_PATH), read_only=True)
    try:
        stocks = connection.execute(
            """
            SELECT symbol, name, exchange, market
            FROM stocks
            WHERE symbol IN (?, ?, ?)
            """,
            SYMBOLS,
        ).df()
        bars = connection.execute(
            """
            SELECT symbol, date, close, volume
            FROM daily_bars
            WHERE symbol IN (?, ?, ?)
            ORDER BY symbol, date
            """,
            SYMBOLS,
        ).df()
    finally:
        connection.close()

    return stocks, bars


def calculate_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    """清洗日 K，并计算日收益率、5 日均线和 5 日均量。"""

    result = bars.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    result["volume"] = pd.to_numeric(result["volume"], errors="coerce")
    result = result.dropna(subset=["symbol", "date", "close", "volume"])
    result = result.drop_duplicates(subset=["symbol", "date"], keep="last")
    result = result.sort_values(["symbol", "date"])

    result["daily_return_pct"] = (
        result.groupby("symbol")["close"].pct_change() * 100
    )
    result["ma_5"] = result.groupby("symbol")["close"].transform(
        lambda values: values.rolling(5).mean()
    )
    result["volume_ma_5"] = result.groupby("symbol")["volume"].transform(
        lambda values: values.rolling(5).mean()
    )
    return result


def main() -> None:
    stocks, bars = load_data()
    analysis = calculate_indicators(bars)
    analysis = analysis.merge(stocks, on="symbol", how="left", validate="many_to_one")

    # tail 返回的结果可能仍引用原表，copy 后再赋值可避免链式赋值警告。
    latest = analysis.groupby("symbol", as_index=False).tail(1).copy()
    latest["above_ma_5"] = latest["close"] > latest["ma_5"]

    print("=== 最新指标 ===")
    columns = [
        "symbol",
        "name",
        "date",
        "close",
        "daily_return_pct",
        "ma_5",
        "volume_ma_5",
        "above_ma_5",
    ]
    print(latest[columns].round(2).to_string(index=False))

    summary = analysis.groupby(["symbol", "name"], as_index=False).agg(
        trading_days=("date", "count"),
        average_close=("close", "mean"),
        total_volume=("volume", "sum"),
    )
    print("\n=== 区间汇总 ===")
    print(summary.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
