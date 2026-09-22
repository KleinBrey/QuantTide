"""最近 5 日成交量 1.5 倍放量突破策略实现。

总市值大于100亿,ST股除外,科创板除外,北交所除外,
最近5个交易日均成交量 / 最近5个交易日前20个交易日均成交量 >= 1.5,
最近5日涨幅 >= 5%,
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
    StockRepository,
    StockHotDailyRepository,
)

console = Console()

# 让中文对齐正确
pd.set_option("display.unicode.east_asian_width", True)
# 让一些特殊 Unicode 字符也尽量对齐
pd.set_option("display.unicode.ambiguous_as_wide", True)


# 计算因子
INDICATOR_COLUMNS = [
    "symbol",
    "latest_date",
    "latest_close",
    "recent_5d_avg_volume",
    "previous_20d_avg_volume",
    "volume_ratio",
    "latest_5d_pct",
    "latest_1d_pct",
]

# 返回结果
RESULT_COLUMNS = [
    "symbol",
    "name",
    "exchange",
    "market_cap",
    "latest_date",
    "latest_close",
    "recent_5d_avg_volume",
    "previous_20d_avg_volume",
    "volume_ratio",
    "latest_5d_pct",
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

    # 最小市值 100亿
    min_market_cap: float = 10_000_000_000
    # 最近5天的成交量
    recent_volume_days: int = 5
    # 前20天的成交量
    previous_volume_days: int = 20
    # 最近5个交易日均成交量/最近5个交易日前20个交易日均成交量大于等于1.5
    min_volume_ratio: float = 1.5
    # 最近5日涨幅大于等于5%
    min_return_5d_pct: float = 0.05

    @property
    def required_trading_days(self) -> int:
        # 一共需要25天的数据
        return self.recent_volume_days + self.previous_volume_days


class VolumeBreakoutStrategy:

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
        result = self._filter_volume_ratio(result)
        result = self._filter_return(result)
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
        is_big_market_cap = stocks["market_cap"] >= self.config.min_market_cap

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
        bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
        bars["volume"] = pd.to_numeric(bars["volume"], errors="coerce")
        # 去空
        bars = bars.dropna(subset=["trade_date", "close", "volume"])
        bars = bars[(bars["close"] > 0) & (bars["volume"] > 0)]

        return bars

    def calculate_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        """最近5个交易日均成交量/最近5个交易日前20个交易日均成交量大于等于1.5,
        最近5日涨幅大于等于5%"""

        rows: list[dict[str, object]] = []
        # 一共需要25个交易日
        required_days = self.config.required_trading_days
        # 最近5个交易日
        recent_days = self.config.recent_volume_days

        for symbol, symbol_bars in bars.groupby("symbol", sort=False):
            window = (
                symbol_bars.sort_values("trade_date")
                .drop_duplicates(subset="trade_date", keep="last")
                .tail(required_days)
            )
            if len(window) < required_days:
                continue

            # 从0到倒数第5条数据，获取的前20日数据
            previous = window.iloc[:-recent_days]
            # 从倒数第5条数据直到最后，获取的最近5天的数据
            recent = window.iloc[-recent_days:]

            previous_avg_volume = previous["volume"].mean()

            recent_avg_volume = recent["volume"].mean()

            volume_ratio = recent_avg_volume / previous_avg_volume

            recent_1d_pct = window["close"] / window["close"].shift(1) - 1

            # 5日涨幅的series
            recent_5d_pct = window["close"] / window["close"].shift(5) - 1

            # 取最新的值
            latest_1d_pct = recent_1d_pct.iloc[-1]

            latest_5d_pct = recent_5d_pct.iloc[-1]

            rows.append(
                {
                    "symbol": symbol,
                    "latest_date": recent["trade_date"].iloc[-1],
                    "latest_close": recent["close"].iloc[-1],
                    "recent_5d_avg_volume": recent_avg_volume,
                    "previous_20d_avg_volume": previous_avg_volume,
                    "volume_ratio": volume_ratio,
                    "latest_5d_pct": latest_5d_pct,
                    "latest_1d_pct": latest_1d_pct,
                }
            )

        return pd.DataFrame(rows, columns=INDICATOR_COLUMNS)

    def _filter_volume_ratio(self, result: pd.DataFrame) -> pd.DataFrame:
        """保留最近 5 日均量至少是此前 20 日均量 1.5 倍的股票。"""

        return result[result["volume_ratio"] >= self.config.min_volume_ratio]

    def _filter_return(self, result: pd.DataFrame) -> pd.DataFrame:
        """保留最近 5 日涨幅大于等于 5% 的股票"""

        return result[result["latest_5d_pct"] >= self.config.min_return_5d_pct]

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

    return VolumeBreakoutStrategy().select(
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
        selected_stocks = VolumeBreakoutStrategy().select(
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
        display["latest_5d_pct"] = display["latest_5d_pct"] * 100
        display["latest_1d_pct"] = display["latest_1d_pct"] * 100
        console.print(
            display[
                [
                    "symbol",
                    "name",
                    "market_cap",
                    "recent_5d_avg_volume",
                    "previous_20d_avg_volume",
                    "volume_ratio",
                    "latest_5d_pct",
                    "latest_1d_pct",
                    "hot_rank",
                ]
            ].rename(
                columns={
                    "symbol": "股票代码",
                    "name": "股票名称",
                    "market_cap": "市值(亿)",
                    "recent_5d_avg_volume": "最近5日均量",
                    "previous_20d_avg_volume": "此前20日均量",
                    "volume_ratio": "均量比",
                    "latest_5d_pct": "5日涨幅(%)",
                    "latest_1d_pct": "今日涨幅(%)",
                    "hot_rank": "热度排名",
                }
            )
        )
        print(f"\n共筛选出 {len(display)} 只股票")
