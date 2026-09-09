"""最新交易日情绪反转策略实现。

总市值大于100亿,ST股除外,科创板除外,北交所除外,
前一交易日涨跌幅：-5% ~ 0%
最新交易日高开幅度：> 3%
最新交易日涨幅：≥ 3%
按现在个股热度排序

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
PCT_EPSILON = 1e-12

# 让中文对齐正确
pd.set_option("display.unicode.east_asian_width", True)
# 让一些特殊 Unicode 字符也尽量对齐
pd.set_option("display.unicode.ambiguous_as_wide", True)


# 计算因子
INDICATOR_COLUMNS = [
    "symbol",
    "latest_date",
    "latest_open",
    "latest_close",
    "previous_1d_pct",
    "latest_open_gap_pct",
    "latest_1d_pct",
]

# 返回结果
RESULT_COLUMNS = [
    "symbol",
    "name",
    "exchange",
    "market_cap",
    "latest_date",
    "latest_open",
    "latest_close",
    "previous_1d_pct",
    "latest_open_gap_pct",
    "latest_1d_pct",
    "hot_rank",
    "hot_value",
]


def load_market_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """读取本地数据"""

    database = DuckDBDatabase()

    # 全部股票列表
    stocks = StockRepository(database).get_table_data()

    # 全部股票日线数据
    daily_bars = DailyBarRepository(database).get_table_data()

    # 最新股票热度
    hot_stocks = StockHotDailyRepository(database).get_latest()

    # 股票最新动态指标
    stock_daily_basic = StockDailyBasicRepository(database).get_table_data()

    return stocks, daily_bars, hot_stocks, stock_daily_basic


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """策略参数"""

    # 最小市值 100亿（策略要求严格大于）
    min_market_cap: float = 10_000_000_000
    # 前一交易日涨跌幅范围（含边界）
    min_previous_return_1d_pct: float = -0.05
    max_previous_return_1d_pct: float = 0.0
    # 最新交易日高开幅度严格大于 3%
    min_open_gap_pct: float = 0.03
    # 最新交易日涨幅大于等于 3%
    min_return_1d_pct: float = 0.03

    @property
    def required_trading_days(self) -> int:
        # 计算昨日涨跌幅需要最近 3 个交易日的数据
        return 3


class TodayEmotionReversalStrategy:

    def __init__(self):
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

        # 获取最新历史交易日
        latest_trade_date = (
            pd.to_datetime(daily_bars["trade_date"]).max().strftime("%Y%m%d")
        )

        # 合并股票市值动态字段
        stocks = self.merge_stock_basic(stocks, stock_daily_basic)
        # 过滤掉 ST、科创板和北交所股票
        stocks = self.filter_stocks(stocks)

        # 返回符合条件的股票的行情数据
        daily_bars = self.filter_daily_bars(daily_bars, stocks["symbol"])
        # 计算指标
        daily_bars = self.calculate_indicators(daily_bars)

        # 筛选过滤排序
        result = stocks.merge(daily_bars, on="symbol", how="inner")
        result = result[result["latest_date"] == pd.to_datetime(latest_trade_date)]
        result = self._filter_previous_return(result)
        result = self._filter_open_gap(result)
        result = self._filter_latest_return(result)
        return self._sort_filter_by_hot(result, hot_stocks)

    @staticmethod
    def merge_stock_basic(
        stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """补齐股票市值动态字段。"""

        return stocks.merge(stock_daily_basic, on="symbol", how="left")

    def filter_stocks(self, stocks: pd.DataFrame) -> pd.DataFrame:
        """排除 ST、科创板和北交所股票。"""

        # 是否是ST
        is_st = stocks["name"].str.contains("ST", na=False)
        # 是否科创板
        is_star_market = stocks["market"] == "科创板"
        # 是否北交所
        is_beijing = stocks["exchange"] == "BJ"
        # 是否符合市值
        is_big_market_cap = stocks["market_cap"] > self.config.min_market_cap

        result = stocks.loc[~is_st & ~is_star_market & ~is_beijing & is_big_market_cap]

        return result

    @staticmethod
    def filter_daily_bars(
        daily_bars: pd.DataFrame,
        symbols: pd.Series,
    ) -> pd.DataFrame:
        """整理行情字段，并只保留候选股票的有效行情。"""

        bars = daily_bars.copy()
        # 只处理符合条件的symbol的数据
        bars = bars[bars["symbol"].isin(symbols)]
        # 格式化
        bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="coerce")
        bars["open"] = pd.to_numeric(bars["open"], errors="coerce")
        bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
        # 去空
        bars = bars.dropna(subset=["trade_date", "open", "close"])
        bars = bars[(bars["open"] > 0) & (bars["close"] > 0)]

        return bars

    def calculate_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        """计算前一日涨幅、最新交易日高开幅度和涨幅。"""

        rows: list[dict[str, object]] = []
        required_days = self.config.required_trading_days

        for symbol, symbol_bars in bars.groupby("symbol", sort=False):
            window = (
                symbol_bars.sort_values("trade_date")
                .drop_duplicates(subset="trade_date", keep="last")
                .tail(required_days)
            )
            if len(window) < required_days:
                continue

            before_previous = window.iloc[-3]
            previous = window.iloc[-2]
            latest = window.iloc[-1]

            previous_1d_pct = previous["close"] / before_previous["close"] - 1
            latest_open_gap_pct = latest["open"] / previous["close"] - 1
            latest_1d_pct = latest["close"] / previous["close"] - 1

            rows.append(
                {
                    "symbol": symbol,
                    "latest_date": latest["trade_date"],
                    "latest_open": latest["open"],
                    "latest_close": latest["close"],
                    "previous_1d_pct": previous_1d_pct,
                    "latest_open_gap_pct": latest_open_gap_pct,
                    "latest_1d_pct": latest_1d_pct,
                }
            )

        return pd.DataFrame(rows, columns=INDICATOR_COLUMNS)

    def _filter_previous_return(self, result: pd.DataFrame) -> pd.DataFrame:
        """保留前一交易日涨跌幅在 -5% 到 0% 之间的股票。"""

        return result[
            result["previous_1d_pct"].between(
                self.config.min_previous_return_1d_pct - PCT_EPSILON,
                self.config.max_previous_return_1d_pct + PCT_EPSILON,
                inclusive="both",
            )
        ]

    def _filter_open_gap(self, result: pd.DataFrame) -> pd.DataFrame:
        """保留最新交易日高开幅度严格大于 3% 的股票。"""

        return result[
            result["latest_open_gap_pct"]
            > self.config.min_open_gap_pct + PCT_EPSILON
        ]

    def _filter_latest_return(self, result: pd.DataFrame) -> pd.DataFrame:
        """保留最新交易日涨幅大于等于 3% 的股票。"""

        return result[
            result["latest_1d_pct"]
            >= self.config.min_return_1d_pct - PCT_EPSILON
        ]

    @staticmethod
    def _sort_filter_by_hot(
        result: pd.DataFrame, hot_stocks: pd.DataFrame
    ) -> pd.DataFrame:
        """按热度进行筛选和排序"""

        if result.empty or hot_stocks.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)

        hot_stocks = hot_stocks.drop_duplicates("symbol").reset_index(drop=True)
        hot_stocks["hot_rank"] = hot_stocks.index + 1

        return (
            result.merge(hot_stocks[["symbol", "hot_rank", "hot_value"]], on="symbol")
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

    return TodayEmotionReversalStrategy().select(
        stocks,
        daily_bars,
        hot_stocks,
        stock_daily_basic,
    )


if __name__ == "__main__":
    with console.status("[bold green]正在请求股票数据..."):
        stocks, daily_bars, hot_stocks, stock_daily_basic = load_market_data()
        # 数据库最新交易日
        latest_trade_date = (
            pd.to_datetime(daily_bars["trade_date"]).max().strftime("%Y-%m-%d")
        )
        console.rule(f"今日:{date.today():%Y-%m-%d} 最新交易日:{latest_trade_date}")
        selected_stocks = TodayEmotionReversalStrategy().select(
            stocks,
            daily_bars,
            hot_stocks,
            stock_daily_basic,
        )
    console.print("[green]✓ 请求完成[/green]")
    if selected_stocks.empty:
        print("没有股票符合策略条件")
    else:
        # 不显示整列为空的可选字段（例如当前数据没有 heat）。
        display = selected_stocks.dropna(axis="columns", how="all")
        display["market_cap"] = (display["market_cap"] / 1e8).round(2)
        display["previous_1d_pct"] = display["previous_1d_pct"] * 100
        display["latest_open_gap_pct"] = display["latest_open_gap_pct"] * 100
        display["latest_1d_pct"] = display["latest_1d_pct"] * 100
        console.print(
            display[
                [
                    "symbol",
                    "name",
                    "market_cap",
                    "previous_1d_pct",
                    "latest_open_gap_pct",
                    "latest_1d_pct",
                    "hot_rank",
                ]
            ].rename(
                columns={
                    "symbol": "股票代码",
                    "name": "股票名称",
                    "market_cap": "市值(亿)",
                    "previous_1d_pct": "前一交易日涨跌幅(%)",
                    "latest_open_gap_pct": "最新交易日高开幅度(%)",
                    "latest_1d_pct": "最新交易日涨幅(%)",
                    "hot_rank": "热度排名",
                }
            )
        )
        print(f"\n共筛选出 {len(display)} 只股票")
