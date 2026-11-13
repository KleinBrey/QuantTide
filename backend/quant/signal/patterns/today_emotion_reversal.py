"""识别最新交易日情绪反转信号。

总市值大于100亿,ST股除外,科创板除外,北交所除外,
前一交易日涨跌幅：-5% ~ 0%
最新交易日高开幅度：> 3%
最新交易日涨幅：≥ 3%
按现在个股热度排序

"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import pandas as pd
from rich.console import Console

from backend.quant.signal.range_utils import (
    DateLike, normalize_trade_dates, select_by_snapshot, trim_history_bars,
)

from backend.app.database import DuckDBDatabase
from backend.app.repository import (
    DailyBarRepository,
    DailyBasicRepository,
    DailyHotRepository,
    DailyStockRepository,
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
    latest_stocks = DailyStockRepository(database).get_latest_data()

    # 全部股票日线数据
    daily_bars = DailyBarRepository(database).get_table_data()

    # 最新股票热度
    latest_hot = DailyHotRepository(database).get_latest_data()

    # 股票最新动态指标
    latest_basic = DailyBasicRepository(database).get_latest_data()

    return latest_stocks, daily_bars, latest_hot, latest_basic


@dataclass(frozen=True, slots=True)
class SignalConfig:
    """信号识别参数。"""

    # 最小市值 100 亿（信号条件要求严格大于）。
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


class TodayEmotionReversalPattern:

    def __init__(self):
        self.config = SignalConfig()

    def scan(
        self,
        latest_stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        latest_hot: pd.DataFrame,
        latest_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """计算指标并返回符合全部条件的股票。"""

        if latest_stocks.empty or daily_bars.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)

        # 获取最新历史交易日
        latest_trade_date = (
            pd.to_datetime(daily_bars["trade_date"]).max().strftime("%Y%m%d")
        )

        # 合并股票市值动态字段
        latest_stocks = self.merge_stock_basic(latest_stocks, latest_basic)
        # 过滤掉 ST、科创板和北交所股票
        latest_stocks = self.filter_stocks(latest_stocks)

        # 返回符合条件的股票的行情数据
        daily_bars = self.filter_daily_bars(daily_bars, latest_stocks["symbol"])
        # 计算指标
        daily_bars = self.calculate_indicators(daily_bars)

        # 筛选过滤排序
        result = latest_stocks.merge(daily_bars, on="symbol", how="inner")
        result = result[result["latest_date"] == pd.to_datetime(latest_trade_date)]
        result = self._filter_previous_return(result)
        result = self._filter_open_gap(result)
        result = self._filter_latest_return(result)
        return self._sort_filter_by_hot(result, latest_hot)

    @staticmethod
    def merge_stock_basic(
        latest_stocks: pd.DataFrame,
        latest_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """补齐股票市值动态字段。"""

        return latest_stocks.drop(columns=["trade_date", "update_time"], errors="ignore").merge(latest_basic, on="symbol", how="left")

    def filter_stocks(self, latest_stocks: pd.DataFrame) -> pd.DataFrame:
        """排除 ST、科创板和北交所股票。"""

        # 是否是ST
        is_st = latest_stocks["name"].str.contains("ST", na=False)
        # 是否科创板
        is_star_market = latest_stocks["market"] == "科创板"
        # 是否北交所
        is_beijing = latest_stocks["exchange"] == "BJ"
        # 是否符合市值
        is_big_market_cap = latest_stocks["market_cap"] > self.config.min_market_cap

        result = latest_stocks.loc[~is_st & ~is_star_market & ~is_beijing & is_big_market_cap]

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

    def scan_range(
        self,
        trade_dates: Iterable[DateLike],
        historical_stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        historical_hot: pd.DataFrame,
        historical_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """批量计算区间指标，再按信号日快照执行本策略筛选与排序。"""
        trade_dates = normalize_trade_dates(trade_dates)
        if trade_dates.empty or daily_bars.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)
        # 先清洗、去重，再保留首个扫描日前真正需要的有效交易日。
        bars = self.filter_daily_bars(daily_bars, daily_bars["symbol"].unique())
        bars = bars.sort_values(["symbol", "trade_date"], kind="stable")
        bars = bars.drop_duplicates(["symbol", "trade_date"], keep="last")
        bars = trim_history_bars(
            bars, trade_dates, lookback_rows=self.config.required_trading_days - 1,
        )
        indicators = self.calculate_range_indicators(bars)
        indicators = indicators[indicators["latest_date"].isin(trade_dates)]
        return select_by_snapshot(
            indicators, historical_stocks, historical_hot, historical_basic,
            self.select_indicators,
        )

    def calculate_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        """复用批量指标，只取每只股票最后一个有效交易日。"""
        indicators = self.calculate_range_indicators(bars)
        return indicators.groupby("symbol", sort=False).tail(1).reset_index(drop=True)

    def calculate_range_indicators(self, daily_bars: pd.DataFrame) -> pd.DataFrame:
        """按股票一次计算全部交易日，仅要求足够的有效历史行情。"""
        bars = daily_bars.sort_values(["symbol", "trade_date"], kind="stable").copy()
        bars = self.filter_daily_bars(bars, bars["symbol"].unique())
        bars = bars.drop_duplicates(["symbol", "trade_date"], keep="last").reset_index(drop=True)
        if bars.empty:
            return pd.DataFrame(columns=INDICATOR_COLUMNS)

        groups = bars.groupby("symbol", sort=False)

        result = pd.DataFrame({
            "symbol": bars["symbol"], "latest_date": bars["trade_date"],
            "latest_close": bars["close"],
        })
        previous_close = groups["close"].shift()
        result["latest_open"] = bars["open"]
        result["previous_1d_pct"] = previous_close / groups["close"].shift(2) - 1
        result["latest_open_gap_pct"] = bars["open"] / previous_close - 1
        result["latest_1d_pct"] = bars["close"] / previous_close - 1
        valid = groups.cumcount() >= self.config.required_trading_days - 1
        return result.loc[valid, INDICATOR_COLUMNS]

    def select_indicators(self, indicators, stocks, basic, hot) -> pd.DataFrame:
        """将批量指标与当日快照合并，复用原筛选条件和排名。"""
        candidates = self.filter_stocks(self.merge_stock_basic(stocks, basic))
        result = candidates.merge(indicators, on="symbol", how="inner")
        result = self._filter_latest_return(self._filter_open_gap(self._filter_previous_return(result)))
        return self._sort_filter_by_hot(result, hot)

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
        result: pd.DataFrame, latest_hot: pd.DataFrame
    ) -> pd.DataFrame:
        """按热度进行筛选和排序"""

        if result.empty or latest_hot.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)

        latest_hot = latest_hot.drop_duplicates("symbol").reset_index(drop=True)
        latest_hot["hot_rank"] = latest_hot["rank"]

        return (
            result.merge(latest_hot[["symbol", "hot_rank"]], on="symbol")
            .sort_values("hot_rank")[RESULT_COLUMNS]
            .reset_index(drop=True)
        )


def run_signal(
    *,
    latest_stocks: pd.DataFrame,
    daily_bars: pd.DataFrame,
    latest_hot: pd.DataFrame,
    latest_basic: pd.DataFrame,
) -> pd.DataFrame:
    """供信号 API 调用的形态识别入口。"""

    return TodayEmotionReversalPattern().scan(
        latest_stocks,
        daily_bars,
        latest_hot,
        latest_basic,
    )


if __name__ == "__main__":
    with console.status("[bold green]正在请求股票数据..."):
        latest_stocks, daily_bars, latest_hot, latest_basic = load_market_data()
        # 数据库最新交易日
        latest_trade_date = (
            pd.to_datetime(daily_bars["trade_date"]).max().strftime("%Y-%m-%d")
        )
        console.rule(f"今日:{date.today():%Y-%m-%d} 最新交易日:{latest_trade_date}")
        selected_stocks = TodayEmotionReversalPattern().scan(
            latest_stocks,
            daily_bars,
            latest_hot,
            latest_basic,
        )
    console.print("[green]✓ 请求完成[/green]")
    if selected_stocks.empty:
        print("没有股票符合信号条件")
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
