"""均线空头排列的近期放量策略。

总市值大于 100 亿，排除 ST、科创板和北交所股票；
最新交易日满足 20 日线大于 10 日线、10 日线大于 5 日线；
最近 3 个交易日均量 / 此前 20 个交易日均量 >= 1.5；
最新收盘价高于最近 3 根 K 线的最低点；
按当前个股热度排序。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from rich.console import Console

from backend.app.database import DuckDBDatabase
from backend.app.repository import (
    DailyBarRepository,
    StockDailyBasicRepository,
    StockHotDailyRepository,
    StockRepository,
)

console = Console()

# 让中文和特殊 Unicode 字符在终端表格中尽量正确对齐。
pd.set_option("display.unicode.east_asian_width", True)
pd.set_option("display.unicode.ambiguous_as_wide", True)


INDICATOR_COLUMNS = [
    "symbol",
    "latest_date",
    "latest_close",
    "ma5",
    "ma10",
    "ma20",
    "recent_3d_low",
    "recent_3d_avg_volume",
    "previous_20d_avg_volume",
    "volume_ratio",
]

RESULT_COLUMNS = [
    "symbol",
    "name",
    "exchange",
    "market_cap",
    "latest_date",
    "latest_close",
    "ma5",
    "ma10",
    "ma20",
    "recent_3d_low",
    "recent_3d_avg_volume",
    "previous_20d_avg_volume",
    "volume_ratio",
    "hot_rank",
    "hot_value",
]


def load_market_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """读取本地数据。"""

    database = DuckDBDatabase()
    stocks = StockRepository(database).get_table_data()
    daily_bars = DailyBarRepository(database).get_table_data()
    hot_stocks = StockHotDailyRepository(database).get_latest()
    stock_daily_basic = StockDailyBasicRepository(database).get_table_data()
    return stocks, daily_bars, hot_stocks, stock_daily_basic


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """策略参数。"""

    # 最小市值 100 亿，筛选时使用严格大于。
    min_market_cap: float = 10_000_000_000
    # 最近 3 个交易日的成交量。
    recent_volume_days: int = 3
    # 最近 3 个交易日前 20 个交易日的成交量。
    previous_volume_days: int = 20
    # 最近 3 日均量 / 此前 20 日均量大于等于 1.5。
    min_volume_ratio: float = 1.5

    @property
    def required_trading_days(self) -> int:
        return self.recent_volume_days + self.previous_volume_days


class PanicReversalVStrategy:
    def __init__(self) -> None:
        self.config = StrategyConfig()

    def select(
        self,
        stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        hot_stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """计算指标并返回符合全部条件的股票。"""

        if stocks.empty or daily_bars.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)

        stocks = self.merge_stock_basic(stocks, stock_daily_basic)
        stocks = self.filter_stocks(stocks)
        if stocks.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)

        daily_bars = self.filter_daily_bars(daily_bars, stocks["symbol"])
        indicators = self.calculate_indicators(daily_bars)

        result = stocks.merge(indicators, on="symbol", how="inner")
        result = self.filter_indicators(result)
        return self._sort_filter_by_hot(result, hot_stocks)

    @staticmethod
    def merge_stock_basic(
        stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """补齐股票市值字段。"""

        return stocks.merge(stock_daily_basic, on="symbol", how="left")

    def filter_stocks(self, stocks: pd.DataFrame) -> pd.DataFrame:
        """保留大市值股票，并排除 ST、科创板和北交所股票。"""

        is_st = stocks["name"].str.contains("ST", case=False, na=False)
        is_star_market = stocks["market"] == "科创板"
        is_beijing = stocks["exchange"] == "BJ"
        is_big_market_cap = stocks["market_cap"] > self.config.min_market_cap

        return stocks.loc[~is_st & ~is_star_market & ~is_beijing & is_big_market_cap]

    @staticmethod
    def filter_daily_bars(
        daily_bars: pd.DataFrame,
        symbols: pd.Series,
    ) -> pd.DataFrame:
        """整理行情字段，并只保留候选股票的有效行情。"""

        bars = daily_bars[daily_bars["symbol"].isin(symbols)].copy()
        bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="coerce")
        bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
        bars["low"] = pd.to_numeric(bars["low"], errors="coerce")
        bars["volume"] = pd.to_numeric(bars["volume"], errors="coerce")
        bars = bars.dropna(subset=["trade_date", "close", "low", "volume"])
        return bars[
            (bars["close"] > 0) & (bars["low"] > 0) & (bars["volume"] > 0)
        ]

    def calculate_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        """计算最新均线和前 20 日、近 3 日的均量比。"""

        rows: list[dict[str, object]] = []
        required_days = self.config.required_trading_days
        recent_days = self.config.recent_volume_days

        for symbol, symbol_bars in bars.groupby("symbol", sort=False):
            window = (
                symbol_bars.sort_values("trade_date")
                .drop_duplicates(subset="trade_date", keep="last")
                .tail(required_days)
            )
            if len(window) < required_days:
                continue

            previous = window.iloc[:-recent_days]
            recent = window.iloc[-recent_days:]
            previous_avg_volume = previous["volume"].mean()
            recent_avg_volume = recent["volume"].mean()

            rows.append(
                {
                    "symbol": symbol,
                    "latest_date": window["trade_date"].iloc[-1],
                    "latest_close": window["close"].iloc[-1],
                    "ma5": window["close"].tail(5).mean(),
                    "ma10": window["close"].tail(10).mean(),
                    "ma20": window["close"].tail(20).mean(),
                    "recent_3d_low": recent["low"].min(),
                    "recent_3d_avg_volume": recent_avg_volume,
                    "previous_20d_avg_volume": previous_avg_volume,
                    "volume_ratio": recent_avg_volume / previous_avg_volume,
                }
            )

        return pd.DataFrame(rows, columns=INDICATOR_COLUMNS)

    def filter_indicators(self, result: pd.DataFrame) -> pd.DataFrame:
        """保留均线空头排列且近 3 日均量放大的股票。"""

        return result.loc[
            (result["ma20"] > result["ma10"])
            & (result["ma10"] > result["ma5"])
            & (result["volume_ratio"] >= self.config.min_volume_ratio)
            & (result["latest_close"] > result["recent_3d_low"])
        ]

    @staticmethod
    def _sort_filter_by_hot(
        result: pd.DataFrame,
        hot_stocks: pd.DataFrame,
    ) -> pd.DataFrame:
        """只保留当前热度榜股票，并按热度排名排序。"""

        if result.empty or hot_stocks.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)

        hot_stocks = hot_stocks.drop_duplicates("symbol").reset_index(drop=True)
        hot_stocks["hot_rank"] = hot_stocks.index + 1

        return (
            result.merge(
                hot_stocks[["symbol", "hot_rank", "hot_value"]],
                on="symbol",
            )
            .sort_values("hot_rank")[RESULT_COLUMNS]
            .reset_index(drop=True)
        )


def run_strategy(
    *,
    stocks: pd.DataFrame,
    daily_bars: pd.DataFrame,
    hot_stocks: pd.DataFrame,
    stock_daily_basic: pd.DataFrame,
) -> pd.DataFrame:
    """供 API 调用的策略入口。"""

    return PanicReversalVStrategy().select(
        stocks,
        daily_bars,
        hot_stocks,
        stock_daily_basic,
    )


if __name__ == "__main__":
    with console.status("[bold green]正在读取本地数据并计算策略..."):
        stocks, daily_bars, hot_stocks, stock_daily_basic = load_market_data()
        latest_date = pd.to_datetime(daily_bars["trade_date"]).max()
        latest_trade_date = (
            latest_date.strftime("%Y-%m-%d") if pd.notna(latest_date) else "无数据"
        )
        selected_stocks = PanicReversalVStrategy().select(
            stocks,
            daily_bars,
            hot_stocks,
            stock_daily_basic,
        )

    console.rule(f"今日:{date.today():%Y-%m-%d} 最新交易日:{latest_trade_date}")
    console.print("[green]✓ 策略计算完成[/green]")

    if selected_stocks.empty:
        console.print("[yellow]没有股票符合策略条件。[/yellow]")
    else:
        display = selected_stocks.copy()
        display["market_cap"] = (display["market_cap"] / 1e8).round(2)
        for column in [
            "latest_close",
            "ma5",
            "ma10",
            "ma20",
            "recent_3d_low",
            "volume_ratio",
        ]:
            display[column] = display[column].round(2)

        console.print(
            display[
                [
                    "symbol",
                    "name",
                    "market_cap",
                    "latest_close",
                    "ma5",
                    "ma10",
                    "ma20",
                    "recent_3d_low",
                    "recent_3d_avg_volume",
                    "previous_20d_avg_volume",
                    "volume_ratio",
                    "hot_rank",
                ]
            ].rename(
                columns={
                    "symbol": "股票代码",
                    "name": "股票名称",
                    "market_cap": "市值(亿)",
                    "latest_close": "最新价",
                    "ma5": "5日线",
                    "ma10": "10日线",
                    "ma20": "20日线",
                    "recent_3d_low": "最近3根最低点",
                    "recent_3d_avg_volume": "最近3日均量",
                    "previous_20d_avg_volume": "此前20日均量",
                    "volume_ratio": "均量比",
                    "hot_rank": "热度排名",
                }
            )
        )
        console.print(f"[green]共筛选出 {len(display)} 只股票。[/green]")
