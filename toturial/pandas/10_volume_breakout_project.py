"""Pandas 第 10 课：使用本地日 K 完成一个简化的放量上涨选股项目。"""

from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "data" / "cn_market.duckdb"

RECENT_DAYS = 5
PREVIOUS_DAYS = 20
MIN_VOLUME_RATIO = 1.5
MIN_RETURN_5D_PCT = 5.0


def load_recent_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """只读取最近 30 个交易日，避免加载整张日 K 表。"""

    connection = duckdb.connect(str(DATABASE_PATH), read_only=True)
    try:
        start_date = connection.execute(
            """
            SELECT min(date)
            FROM (
                SELECT DISTINCT date
                FROM daily_bars
                ORDER BY date DESC
                LIMIT 30
            )
            """
        ).fetchone()[0]

        stocks = connection.execute(
            "SELECT symbol, name, exchange, market FROM stocks"
        ).df()
        bars = connection.execute(
            """
            SELECT symbol, date, close, volume
            FROM daily_bars
            WHERE date >= ?
            ORDER BY symbol, date
            """,
            [start_date],
        ).df()
    finally:
        connection.close()

    return stocks, bars


def calculate_volume_breakout(bars: pd.DataFrame) -> pd.DataFrame:
    """逐只股票计算 5 日/前 20 日量比和 5 日涨幅。"""

    rows: list[dict[str, object]] = []
    required_days = RECENT_DAYS + PREVIOUS_DAYS

    for symbol, symbol_bars in bars.groupby("symbol"):
        window = symbol_bars.drop_duplicates("date", keep="last").tail(required_days)
        if len(window) < required_days:
            continue

        previous = window.iloc[:PREVIOUS_DAYS]
        recent = window.iloc[-RECENT_DAYS:]

        previous_average_volume = previous["volume"].mean()
        recent_average_volume = recent["volume"].mean()
        base_close = previous.iloc[-1]["close"]
        latest = recent.iloc[-1]

        rows.append(
            {
                "symbol": symbol,
                "latest_date": latest["date"],
                "latest_close": latest["close"],
                "volume_ratio": recent_average_volume / previous_average_volume,
                "return_5d_pct": (latest["close"] / base_close - 1) * 100,
            }
        )

    return pd.DataFrame(rows)


def main() -> None:
    stocks, bars = load_recent_data()
    indicators = calculate_volume_breakout(bars)
    result = indicators.merge(stocks, on="symbol", how="left", validate="one_to_one")

    # 与项目策略一致：排除 ST、科创板和北交所股票。
    is_st = result["name"].fillna("").str.upper().str.contains("ST", regex=False)
    is_star = result["market"].eq("科创板") | result["symbol"].str.startswith("688")
    is_beijing = result["exchange"].eq("BJ")
    result = result.loc[~is_st & ~is_star & ~is_beijing]

    selected = result.loc[
        (result["volume_ratio"] >= MIN_VOLUME_RATIO)
        & (result["return_5d_pct"] > MIN_RETURN_5D_PCT)
    ]
    selected = selected.sort_values(
        ["volume_ratio", "return_5d_pct"], ascending=False
    ).reset_index(drop=True)

    print(
        f"条件：量比 >= {MIN_VOLUME_RATIO}，"
        f"5 日涨幅 > {MIN_RETURN_5D_PCT}%"
    )
    print(f"候选股票数量：{len(selected)}")

    if selected.empty:
        print("当前没有股票同时满足条件，可以调低文件顶部的两个阈值再运行。")
    else:
        columns = [
            "symbol",
            "name",
            "latest_date",
            "latest_close",
            "volume_ratio",
            "return_5d_pct",
        ]
        print(selected[columns].head(20).round(2).to_string(index=False))


if __name__ == "__main__":
    main()

# 真实策略还会使用市值和热度。它们需要额外数据源，本节只讲本地 Pandas 部分。
