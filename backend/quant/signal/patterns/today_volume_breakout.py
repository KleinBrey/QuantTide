"""识别最新交易日成交量 2 倍放量突破信号。

筛选条件:
1. 总市值大于 100 亿,排除 ST、科创板、北交所
2. 最新交易日涨幅大于 0
3. 最新交易日成交量 / 前 10 个交易日均成交量 >= 2
4. 按当前个股热度排序
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import numpy as np
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
from backend.quant.stock import filter_stocks

# ============================================================
# 一、全局设置与列定义
# ============================================================

console = Console()

# 让中文对齐正确
pd.set_option("display.unicode.east_asian_width", True)
pd.set_option("display.unicode.ambiguous_as_wide", True)

# 指标计算阶段的输出列
INDICATOR_COLUMNS = [
    "symbol",
    "latest_date",
    "latest_close",
    "latest_volume",
    "previous_10d_avg_volume",
    "volume_ratio",
    "latest_1d_pct",
]

# 最终返回结果的列
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

# 终端展示:列顺序 + 中文表头
DISPLAY_COLUMNS = {
    "symbol": "股票代码",
    "name": "股票名称",
    "market_cap": "市值(亿)",
    "latest_volume": "最新交易日成交量",
    "previous_10d_avg_volume": "前10日均量",
    "volume_ratio": "量比",
    "latest_1d_pct": "最新交易日涨幅(%)",
    "hot_rank": "热度排名",
}


# ============================================================
# 二、信号参数
# ============================================================


@dataclass(frozen=True, slots=True)
class SignalConfig:
    """信号识别参数。"""

    # 最小市值 100 亿(要求严格大于)
    min_market_cap: float = 10_000_000_000
    # 最新交易日的天数(即 1 天)
    recent_volume_days: int = 1
    # 参与均量计算的前序交易日数
    previous_volume_days: int = 10
    # 量比阈值:最新成交量 / 前 10 日均量 >= 2
    min_volume_ratio: float = 2.0
    # 最新交易日涨幅需大于 0
    min_return_1d_pct: float = 0.0

    @property
    def required_trading_days(self) -> int:
        """每只股票至少需要的交易日数量(这里为 11 天)。"""
        return self.recent_volume_days + self.previous_volume_days


# ============================================================
# 三、形态识别:扫描流水线
# ============================================================


class TodayVolumeBreakoutPattern:
    """最新交易日放量突破形态。

    scan() 流水线:
        候选股票 -> 清洗行情 -> 计算指标 -> 量比过滤 -> 涨幅过滤 -> 热度排序
    """

    def __init__(self, config: SignalConfig | None = None):
        self.config = config or SignalConfig()

    # ---------- 入口 ----------

    def scan(
        self,
        latest_stocks: pd.DataFrame,
        latest_basic: pd.DataFrame,
        latest_hot: pd.DataFrame,
        daily_bars: pd.DataFrame,
    ) -> pd.DataFrame:
        """计算指标并返回符合全部条件的股票。"""

        if latest_stocks.empty or daily_bars.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)

        # 1. 基础筛选:市值、ST、科创板、北交所
        candidates = filter_stocks(
            self.config.min_market_cap,
            latest_stocks,
            latest_basic,
        )

        # 2. 只保留候选股票的有效行情
        bars = self.clean_daily_bars(daily_bars, candidates["symbol"])

        # 3. 计算量比、涨幅等指标
        indicators = self.calculate_indicators(bars)

        # 4. 合并后按条件过滤
        result = candidates.merge(indicators, on="symbol", how="inner")
        result = self._filter_volume_ratio(result)
        result = self._filter_return(result)

        # 5. 按热度排序
        return self._sort_by_hot(result, latest_hot)

    # ---------- 步骤 2:行情清洗 ----------

    @staticmethod
    def clean_daily_bars(
        daily_bars: pd.DataFrame,
        symbols: pd.Series,
    ) -> pd.DataFrame:
        """整理行情字段,只保留候选股票的有效行情。"""

        # copy() 避免对切片赋值触发 SettingWithCopyWarning
        bars = daily_bars[daily_bars["symbol"].isin(symbols)].copy()

        # 类型转换
        bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="coerce")
        bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
        bars["volume"] = pd.to_numeric(bars["volume"], errors="coerce")

        # 去除空值与无效数据
        bars = bars.dropna(subset=["trade_date", "close", "volume"])
        return bars[(bars["close"] > 0) & (bars["volume"] > 0)]

    # ---------- 步骤 3:指标计算 ----------

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
        bars = self.clean_daily_bars(daily_bars, daily_bars["symbol"].unique())
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
        bars = self.clean_daily_bars(bars, bars["symbol"].unique())
        bars = bars.drop_duplicates(["symbol", "trade_date"], keep="last").reset_index(drop=True)
        if bars.empty:
            return pd.DataFrame(columns=INDICATOR_COLUMNS)

        groups = bars.groupby("symbol", sort=False)

        def rolling(column, days, operation):
            # NumPy 窗口批量归约保留原逐窗口 mean 的求和顺序，
            # 避免 rolling 累积误差改变均线相等、量比恰好达标等边界。
            values = bars[column].to_numpy(dtype=float)
            result = pd.Series(np.nan, index=bars.index)
            if len(values) >= days:
                windows = np.lib.stride_tricks.sliding_window_view(values, days)
                result.iloc[days - 1:] = getattr(windows, operation)(axis=1)
            return result.where(groups.cumcount() >= days - 1)

        result = pd.DataFrame({
            "symbol": bars["symbol"], "latest_date": bars["trade_date"],
            "latest_close": bars["close"],
        })
        recent = self.config.recent_volume_days
        previous = self.config.previous_volume_days
        averages = rolling("volume", previous, "mean").groupby(bars["symbol"], sort=False).shift(recent)
        result["latest_volume"] = bars["volume"]
        result["previous_10d_avg_volume"] = averages
        result["volume_ratio"] = bars["volume"] / averages
        result["latest_1d_pct"] = bars["close"] / groups["close"].shift(recent) - 1
        valid = groups.cumcount() >= self.config.required_trading_days - 1
        return result.loc[valid, INDICATOR_COLUMNS]

    def select_indicators(self, indicators, stocks, basic, hot) -> pd.DataFrame:
        """将批量指标与当日快照合并，复用原筛选条件和排名。"""
        candidates = filter_stocks(self.config.min_market_cap, stocks, basic)
        result = candidates.merge(indicators, on="symbol", how="inner")
        result = self._filter_return(self._filter_volume_ratio(result))
        return self._sort_by_hot(result, hot)

    def _filter_volume_ratio(self, result: pd.DataFrame) -> pd.DataFrame:
        """保留最新成交量至少是此前 10 日均量 2 倍的股票。"""
        return result[result["volume_ratio"] >= self.config.min_volume_ratio]

    def _filter_return(self, result: pd.DataFrame) -> pd.DataFrame:
        """保留最新交易日涨幅大于 0 的股票。"""
        return result[result["latest_1d_pct"] > self.config.min_return_1d_pct]

    # ---------- 步骤 5:热度排序 ----------

    @staticmethod
    def _sort_by_hot(
        result: pd.DataFrame,
        latest_hot: pd.DataFrame,
    ) -> pd.DataFrame:
        """合并热度排名并升序排列;没有热度数据的股票会被剔除。"""

        if result.empty or latest_hot.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)

        hot = latest_hot.drop_duplicates("symbol").rename(columns={"rank": "hot_rank"})[
            ["symbol", "hot_rank"]
        ]

        return (
            result.merge(hot, on="symbol")
            .sort_values("hot_rank")[RESULT_COLUMNS]
            .reset_index(drop=True)
        )


# ============================================================
# 四、对外接口
# ============================================================


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
        latest_basic,
        latest_hot,
        daily_bars,
    )


# ============================================================
# 五、数据加载
# ============================================================


def load_market_data() -> tuple[
    pd.DataFrame,  # latest_stocks: 全部股票列表
    pd.DataFrame,  # latest_basic:  股票最新动态指标
    pd.DataFrame,  # latest_hot:    最新股票热度
    pd.DataFrame,  # daily_bars:    全部股票日线数据
]:
    """读取本地数据库中的行情数据。"""

    database = DuckDBDatabase()

    latest_stocks = DailyStockRepository(database).get_latest_data()
    latest_basic = DailyBasicRepository(database).get_latest_data()
    latest_hot = DailyHotRepository(database).get_latest_data()
    daily_bars = DailyBarRepository(database).get_table_data()

    return latest_stocks, latest_basic, latest_hot, daily_bars


# ============================================================
# 六、结果展示(命令行)
# ============================================================


def build_display_table(selected: pd.DataFrame) -> pd.DataFrame:
    """把扫描结果转换为适合终端展示的表格。"""

    display = selected.dropna(axis="columns", how="all").copy()
    display["market_cap"] = (display["market_cap"] / 1e8).round(2)
    display["latest_1d_pct"] = display["latest_1d_pct"] * 100

    return display[list(DISPLAY_COLUMNS)].rename(columns=DISPLAY_COLUMNS)


def print_result(selected: pd.DataFrame) -> None:
    """打印筛选结果。"""

    if selected.empty:
        print("没有股票符合信号条件")
        return

    table = build_display_table(selected)
    console.print(table)
    print(f"\n共筛选出 {len(table)} 只股票")


# ============================================================
# 七、命令行入口
# ============================================================


def main() -> None:
    with console.status("[bold green]正在请求股票数据..."):
        latest_stocks, latest_basic, latest_hot, daily_bars = load_market_data()

        latest_trade_date = (
            pd.to_datetime(daily_bars["trade_date"]).max().strftime("%Y-%m-%d")
        )
        console.rule(f"今日:{date.today():%Y-%m-%d} 最新交易日:{latest_trade_date}")

        selected = TodayVolumeBreakoutPattern().scan(
            latest_stocks,
            latest_basic,
            latest_hot,
            daily_bars,
        )
    console.print("[green]✓ 请求完成[/green]")

    print_result(selected)


if __name__ == "__main__":
    main()
