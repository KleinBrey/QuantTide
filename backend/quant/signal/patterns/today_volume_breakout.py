"""识别最新交易日成交量 2 倍放量突破信号。

总市值大于100亿,ST股除外,科创板除外,北交所除外,
最新交易日涨幅大于0,
最新交易日成交量 / 前10个交易日均成交量 >= 2,
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
    DailyBasicRepository,
    DailyHotRepository,
    DailyStockRepository,
)

from backend.quant.stock import filter_stocks

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
    "latest_volume",
    "previous_10d_avg_volume",
    "volume_ratio",
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
    "latest_volume",
    "previous_10d_avg_volume",
    "volume_ratio",
    "latest_1d_pct",
    "hot_rank",
]


@dataclass(frozen=True, slots=True)
class SignalConfig:
    """信号识别参数。"""

    # 最小市值 100 亿（信号条件要求严格大于）。
    min_market_cap: float = 10_000_000_000
    # 最新1个交易日的成交量
    recent_volume_days: int = 1
    # 前10个交易日的成交量
    previous_volume_days: int = 10
    # 最新交易日成交量/前10个交易日均成交量大于等于2
    min_volume_ratio: float = 2.0
    # 最新交易日涨幅大于0
    min_return_1d_pct: float = 0.0

    @property
    def required_trading_days(self) -> int:
        # 一共需要11天的数据
        return self.recent_volume_days + self.previous_volume_days


class TodayVolumeBreakoutPattern:

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

        latest_stocks = filter_stocks(
            self.config.min_market_cap,
            latest_stocks,
            latest_basic,
        )

        # 返回符合条件的股票的行情数据
        daily_bars = self.filter_daily_bars(daily_bars, latest_stocks["symbol"])
        # 计算指标
        daily_bars = self.calculate_indicators(daily_bars)

        # 筛选过滤排序
        result = latest_stocks.merge(daily_bars, on="symbol", how="inner")
        result = self._filter_volume_ratio(result)
        result = self._filter_return(result)
        return self._sort_filter_by_hot(result, latest_hot)

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
        """计算最新交易日量比和涨幅。"""

        rows: list[dict[str, object]] = []
        # 一共需要11个交易日
        required_days = self.config.required_trading_days
        # 最新1个交易日
        recent_days = self.config.recent_volume_days

        for symbol, symbol_bars in bars.groupby("symbol", sort=False):
            window = (
                symbol_bars.sort_values("trade_date")
                .drop_duplicates(subset="trade_date", keep="last")
                .tail(required_days)
            )
            if len(window) < required_days:
                continue

            # 从0到倒数第1条数据，获取前10日数据
            previous = window.iloc[:-recent_days]
            # 取最后1条数据，获取最新交易日数据
            recent = window.iloc[-recent_days:]

            previous_avg_volume = previous["volume"].mean()
            latest_volume = recent["volume"].iloc[-1]
            volume_ratio = latest_volume / previous_avg_volume

            recent_1d_pct = window["close"] / window["close"].shift(1) - 1
            latest_1d_pct = recent_1d_pct.iloc[-1]

            rows.append(
                {
                    "symbol": symbol,
                    "latest_date": recent["trade_date"].iloc[-1],
                    "latest_close": recent["close"].iloc[-1],
                    "latest_volume": latest_volume,
                    "previous_10d_avg_volume": previous_avg_volume,
                    "volume_ratio": volume_ratio,
                    "latest_1d_pct": latest_1d_pct,
                }
            )

        return pd.DataFrame(rows, columns=INDICATOR_COLUMNS)

    def _filter_volume_ratio(self, result: pd.DataFrame) -> pd.DataFrame:
        """保留最新成交量至少是此前 10 日均量 2 倍的股票。"""

        return result[result["volume_ratio"] >= self.config.min_volume_ratio]

    def _filter_return(self, result: pd.DataFrame) -> pd.DataFrame:
        """保留最新交易日涨幅大于 0 的股票。"""

        return result[result["latest_1d_pct"] > self.config.min_return_1d_pct]

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

    return TodayVolumeBreakoutPattern().scan(
        latest_stocks,
        daily_bars,
        latest_hot,
        latest_basic,
    )


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


if __name__ == "__main__":
    with console.status("[bold green]正在请求股票数据..."):
        latest_stocks, daily_bars, latest_hot, latest_basic = load_market_data()
        # 数据库最新交易日
        latest_trade_date = (
            pd.to_datetime(daily_bars["trade_date"]).max().strftime("%Y-%m-%d")
        )
        console.rule(f"今日:{date.today():%Y-%m-%d} 最新交易日:{latest_trade_date}")
        selected_stocks = TodayVolumeBreakoutPattern().scan(
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
        display["latest_1d_pct"] = display["latest_1d_pct"] * 100
        console.print(
            display[
                [
                    "symbol",
                    "name",
                    "market_cap",
                    "latest_volume",
                    "previous_10d_avg_volume",
                    "volume_ratio",
                    "latest_1d_pct",
                    "hot_rank",
                ]
            ].rename(
                columns={
                    "symbol": "股票代码",
                    "name": "股票名称",
                    "market_cap": "市值(亿)",
                    "latest_volume": "最新交易日成交量",
                    "previous_10d_avg_volume": "前10日均量",
                    "volume_ratio": "量比",
                    "latest_1d_pct": "最新交易日涨幅(%)",
                    "hot_rank": "热度排名",
                }
            )
        )
        print(f"\n共筛选出 {len(display)} 只股票")
