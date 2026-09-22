"""前一交易日放量突破、当前交易日小阳线确认策略。

策略分为两个阶段：

1. 用确认日之前的行情寻找最近交易日的放量上涨股票；
2. 用确认日 K 线检查实体、上下影线和量能，生成入场与风控价格。
"""

from __future__ import annotations

import argparse
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

# 突破阶段的纯行情指标；固定列顺序便于空结果也保持稳定的数据结构。
BREAKOUT_INDICATOR_COLUMNS = [
    "symbol",
    "breakout_date",
    "breakout_close",
    "breakout_volume",
    "breakout_previous_10d_avg_volume",
    "breakout_volume_ratio",
    "breakout_return_1d_pct",
]

# 突破指标与股票基本信息、热度信息合并后的中间结果。
BREAKOUT_RESULT_COLUMNS = [
    "symbol",
    "name",
    "exchange",
    "market_cap",
    "breakout_date",
    "breakout_close",
    "breakout_volume",
    "breakout_previous_10d_avg_volume",
    "breakout_volume_ratio",
    "breakout_return_1d_pct",
    "hot_rank",
    "hot_value",
]

# 策略最终向 API 和回测引擎暴露的字段。
RESULT_COLUMNS = [
    "symbol",
    "name",
    "exchange",
    "market_cap",
    "breakout_date",
    "confirm_date",
    "breakout_volume_ratio",
    "breakout_return_1d_pct",
    "confirm_body_pct",
    "confirm_lower_wick_ratio",
    "confirm_upper_wick_ratio",
    "confirm_volume_ratio",
    "confirm_close",
    "stop_loss_price",
    "take_profit_price",
    "risk_per_share",
    "hot_rank",
    "hot_value",
    "selection_rank",
]


@dataclass(frozen=True, slots=True)
class BreakoutStrategyConfig:
    """前一交易日放量突破条件。"""

    # 总市值必须严格大于 100 亿元。
    min_market_cap: float = 10_000_000_000
    # recent 区间是待判断的突破日，当前策略固定取最近 1 日。
    recent_volume_days: int = 1
    # 用突破日之前的 10 个交易日计算基准成交量。
    previous_volume_days: int = 10
    # 突破日成交量至少达到基准均量的 2 倍。
    min_breakout_volume_ratio: float = 2.0
    # 突破日必须收涨；比例使用小数表示，0.03 代表 3%。
    min_breakout_return_1d_pct: float = 0.0

    @property
    def required_trading_days(self) -> int:
        """计算一次突破信号所需的最少交易日数量。"""

        return self.recent_volume_days + self.previous_volume_days


class TodayConfirmedBreakoutStrategy:
    """先计算前一交易日突破股，再用 trade_date 当日 K 线确认。"""

    # 确认日阳线实体涨幅不能超过 3%，避免追入大阳线。
    max_confirm_body_pct = 0.03
    # 下影线至少占整根 K 线振幅的 10%。
    min_confirm_lower_wick_ratio = 0.10
    # 上影线最多占整根 K 线振幅的 15%。
    max_confirm_upper_wick_ratio = 0.15
    # 确认日成交量至少保留突破日成交量的 70%。
    min_confirm_volume_ratio = 0.70
    # 止盈距离为每股风险的 2 倍，即目标盈亏比 2:1。
    risk_reward_ratio = 2.0

    def __init__(self) -> None:
        self.breakout_config = BreakoutStrategyConfig()

    def select(
        self,
        trade_date: date | str | pd.Timestamp,
        stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        hot_stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """返回在 trade_date 当天通过二次确认的股票。"""

        # 统一到零点，避免输入含时分秒时无法与日频数据正确匹配。
        confirm_date = pd.Timestamp(trade_date).normalize()
        bars = daily_bars.copy()
        bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.normalize()

        # 1. 突破阶段只能看到确认日以前的数据，防止使用未来行情。
        history = bars[bars["trade_date"] < confirm_date]
        if history.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)

        # 全市场确认日前最后一个有行情的日期就是预期突破日。
        breakout_date = history["trade_date"].max()

        # 2. 基于历史行情计算放量上涨候选股。
        breakout_stocks = self._select_breakout_candidates(
            stocks,
            history,
            hot_stocks,
            stock_daily_basic,
        )
        # 个股可能停牌；剔除最后一根 K 线早于全市场突破日的股票。
        breakout_stocks = breakout_stocks[
            pd.to_datetime(breakout_stocks["breakout_date"]).dt.normalize()
            == breakout_date
        ]
        if breakout_stocks.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)

        # 3. 只读取候选股的确认日 K 线，减少后续合并的数据量。
        confirm_bars = bars[
            (bars["trade_date"] == confirm_date)
            & (bars["symbol"].isin(breakout_stocks["symbol"]))
        ][["symbol", "open", "high", "low", "close", "volume"]].copy()
        if confirm_bars.empty:
            return pd.DataFrame(columns=RESULT_COLUMNS)

        # 增加 confirm_ 前缀，避免与突破日字段混淆或合并时产生后缀。
        confirm_bars = confirm_bars.rename(
            columns={
                "open": "confirm_open",
                "high": "confirm_high",
                "low": "confirm_low",
                "close": "confirm_close",
                "volume": "confirm_volume",
            }
        )
        result = breakout_stocks.merge(confirm_bars, on="symbol", how="inner")
        return self._confirm(result, confirm_date)

    def _select_breakout_candidates(
        self,
        stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        hot_stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """计算放量突破指标并返回符合全部条件的股票。"""

        if stocks.empty or daily_bars.empty:
            return pd.DataFrame(columns=BREAKOUT_RESULT_COLUMNS)

        # 股票池过滤必须早于指标计算，可避免处理明显不符合条件的股票。
        stocks = self._merge_stock_basic(stocks, stock_daily_basic)
        stocks = self._filter_stocks(stocks)

        # 每只股票只保留有效收盘价和成交量，再计算最近 11 个交易日指标。
        daily_bars = self._filter_daily_bars(daily_bars, stocks["symbol"])
        daily_bars = self._calculate_breakout_indicators(daily_bars)

        # 先做硬性量价过滤，最后用热度决定候选股顺序。
        result = stocks.merge(daily_bars, on="symbol", how="inner")
        result = self._filter_breakout_volume_ratio(result)
        result = self._filter_breakout_return(result)
        return self._sort_filter_by_hot(result, hot_stocks)

    @staticmethod
    def _merge_stock_basic(
        stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """补齐股票市值动态字段。"""

        # 股票主表不含动态市值，因此按 symbol 从每日基础指标表补齐。
        return stocks.merge(stock_daily_basic, on="symbol", how="left")

    def _filter_stocks(self, stocks: pd.DataFrame) -> pd.DataFrame:
        """排除 ST、科创板和北交所股票。"""

        # 分别保留布尔条件，便于以后单独调整某项股票池规则。
        is_st = stocks["name"].str.contains("ST", na=False)
        is_star_market = stocks["market"] == "科创板"
        is_beijing = stocks["exchange"] == "BJ"
        is_big_market_cap = stocks["market_cap"] > self.breakout_config.min_market_cap
        return stocks.loc[~is_st & ~is_star_market & ~is_beijing & is_big_market_cap]

    @staticmethod
    def _filter_daily_bars(
        daily_bars: pd.DataFrame,
        symbols: pd.Series,
    ) -> pd.DataFrame:
        """整理行情字段，并只保留候选股票的有效行情。"""

        bars = daily_bars.copy()
        # 先按股票池裁剪数据，再做类型转换，降低批量计算开销。
        bars = bars[bars["symbol"].isin(symbols)]

        # 无法解析的值会转成 NaT/NaN，并在下一步统一丢弃。
        bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="coerce")
        bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
        bars["volume"] = pd.to_numeric(bars["volume"], errors="coerce")
        bars = bars.dropna(subset=["trade_date", "close", "volume"])
        # 零值和负值无法用于收益率、量比计算。
        return bars[(bars["close"] > 0) & (bars["volume"] > 0)]

    def _calculate_breakout_indicators(
        self,
        bars: pd.DataFrame,
    ) -> pd.DataFrame:
        """计算突破日的量比和单日涨幅。"""

        rows: list[dict[str, object]] = []
        # 默认窗口为“前 10 日基准 + 最近 1 个突破日”。
        required_days = self.breakout_config.required_trading_days
        recent_days = self.breakout_config.recent_volume_days

        for symbol, symbol_bars in bars.groupby("symbol", sort=False):
            # 同一股票同一天只保留最后一条记录，然后截取最近所需窗口。
            window = (
                symbol_bars.sort_values("trade_date")
                .drop_duplicates(subset="trade_date", keep="last")
                .tail(required_days)
            )
            if len(window) < required_days:
                continue

            # previous 用作成交量基准，recent 表示待判断的突破区间。
            previous = window.iloc[:-recent_days]
            recent = window.iloc[-recent_days:]
            previous_avg_volume = previous["volume"].mean()
            breakout_volume = recent["volume"].iloc[-1]

            # 放量倍数 = 突破日成交量 / 此前 10 日平均成交量。
            breakout_volume_ratio = breakout_volume / previous_avg_volume
            # pct_change 的等价写法；最后一个值就是突破日单日涨幅。
            breakout_return_1d_pct = (
                window["close"] / window["close"].shift(1) - 1
            )

            rows.append(
                {
                    "symbol": symbol,
                    "breakout_date": recent["trade_date"].iloc[-1],
                    "breakout_close": recent["close"].iloc[-1],
                    "breakout_volume": breakout_volume,
                    "breakout_previous_10d_avg_volume": previous_avg_volume,
                    "breakout_volume_ratio": breakout_volume_ratio,
                    "breakout_return_1d_pct": breakout_return_1d_pct.iloc[-1],
                }
            )

        return pd.DataFrame(rows, columns=BREAKOUT_INDICATOR_COLUMNS)

    def _filter_breakout_volume_ratio(
        self,
        result: pd.DataFrame,
    ) -> pd.DataFrame:
        """保留突破日成交量至少是此前 10 日均量 2 倍的股票。"""

        return result[
            result["breakout_volume_ratio"]
            >= self.breakout_config.min_breakout_volume_ratio
        ]

    def _filter_breakout_return(self, result: pd.DataFrame) -> pd.DataFrame:
        """保留突破日涨幅大于 0 的股票。"""

        return result[
            result["breakout_return_1d_pct"]
            > self.breakout_config.min_breakout_return_1d_pct
        ]

    @staticmethod
    def _sort_filter_by_hot(
        result: pd.DataFrame,
        hot_stocks: pd.DataFrame,
    ) -> pd.DataFrame:
        """按热度进行筛选和排序。"""

        if result.empty:
            return pd.DataFrame(columns=BREAKOUT_RESULT_COLUMNS)

        result = result.copy()
        if hot_stocks.empty:
            # 历史热度可能缺失，此时不丢弃信号，改按放量强度降序排列。
            result["hot_rank"] = pd.NA
            result["hot_value"] = pd.NA
            return result.sort_values("breakout_volume_ratio", ascending=False)[
                BREAKOUT_RESULT_COLUMNS
            ].reset_index(drop=True)

        # 输入热度表的原始顺序代表排名；同一股票只采用第一条记录。
        hot_stocks = hot_stocks.drop_duplicates("symbol").reset_index(drop=True)
        hot_stocks["hot_rank"] = hot_stocks.index + 1
        return (
            # 左连接保留没有热度记录的突破股，并将它们排在已有热度股之后。
            result.merge(
                hot_stocks[["symbol", "hot_rank", "hot_value"]],
                on="symbol",
                how="left",
            )
            .sort_values(
                ["hot_rank", "breakout_volume_ratio"],
                ascending=[True, False],
                na_position="last",
            )[BREAKOUT_RESULT_COLUMNS]
            .reset_index(drop=True)
        )

    def _confirm(
        self,
        result: pd.DataFrame,
        confirm_date: pd.Timestamp,
    ) -> pd.DataFrame:
        """检查小阳线、上下影线和量能。"""

        # 整根 K 线振幅是两个影线比例的分母，必须严格大于 0。
        candle_range = result["confirm_high"] - result["confirm_low"]
        # 阳线实体涨幅，以确认日开盘价为基准。
        result["confirm_body_pct"] = (
            result["confirm_close"] / result["confirm_open"] - 1
        )
        # 策略只接受阳线，因此开盘价是实体下沿、收盘价是实体上沿。
        result["confirm_lower_wick_ratio"] = (
            result["confirm_open"] - result["confirm_low"]
        ) / candle_range
        result["confirm_upper_wick_ratio"] = (
            result["confirm_high"] - result["confirm_close"]
        ) / candle_range
        # 确认日量能相对于突破日量能的保留比例。
        result["confirm_volume_ratio"] = (
            result["confirm_volume"] / result["breakout_volume"]
        )

        # 必须同时满足：有效振幅、小阳线、影线形态和量能保持。
        result = result[
            (candle_range > 0)
            & (result["confirm_close"] > result["confirm_open"])
            & (result["confirm_body_pct"] <= self.max_confirm_body_pct)
            & (
                result["confirm_lower_wick_ratio"]
                >= self.min_confirm_lower_wick_ratio
            )
            & (
                result["confirm_upper_wick_ratio"]
                <= self.max_confirm_upper_wick_ratio
            )
            & (result["confirm_volume_ratio"] >= self.min_confirm_volume_ratio)
        ].copy()

        # 突破日产生信号，确认日收盘价作为回测入场价。
        result["breakout_date"] = pd.to_datetime(result["breakout_date"])
        result["confirm_date"] = confirm_date

        # breakout_close / (1 + breakout_return_1d_pct) 可还原突破日前收盘价。
        result["stop_loss_price"] = result["breakout_close"] / (
            1 + result["breakout_return_1d_pct"]
        )
        # 每股风险决定仓位的止盈距离；非正风险说明价格关系不成立。
        result["risk_per_share"] = result["confirm_close"] - result["stop_loss_price"]
        result = result[result["risk_per_share"] > 0].copy()
        # 2:1 盈亏比：止盈价 = 入场价 + 2 × 每股风险。
        result["take_profit_price"] = result["confirm_close"] + (
            result["risk_per_share"] * self.risk_reward_ratio
        )
        # 沿用此前热度/量比顺序，生成稳定的候选排名。
        result["selection_rank"] = range(1, len(result) + 1)
        return result[RESULT_COLUMNS].reset_index(drop=True)


def load_market_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """读取本地 A 股数据。"""

    database = DuckDBDatabase()
    return (
        # 股票静态信息：名称、交易所、板块等。
        StockRepository(database).get_table_data(),
        # 全量日 K，用于突破和确认两个阶段。
        DailyBarRepository(database).get_table_data(),
        # 命令行运行使用最新热度快照。
        StockHotDailyRepository(database).get_latest(),
        # 动态基础信息，当前策略使用其中的总市值。
        StockDailyBasicRepository(database).get_table_data(),
    )


def run_strategy(
    *,
    stocks: pd.DataFrame,
    daily_bars: pd.DataFrame,
    hot_stocks: pd.DataFrame,
    stock_daily_basic: pd.DataFrame,
    trade_date: date | str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """供策略 API 调用；未指定日期时使用最新交易日。"""

    # API 未传日期时，将数据库中的最后一个交易日视作确认日。
    trade_date = trade_date or pd.to_datetime(daily_bars["trade_date"]).max()
    return TodayConfirmedBreakoutStrategy().select(
        trade_date,
        stocks,
        daily_bars,
        hot_stocks,
        stock_daily_basic,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行放量突破次日确认策略")
    parser.add_argument("--trade-date", help="确认日期，例如 2025-09-11")
    args = parser.parse_args()

    stocks, daily_bars, hot_stocks, stock_daily_basic = load_market_data()
    trade_date = args.trade_date or pd.to_datetime(daily_bars["trade_date"]).max()
    selected = TodayConfirmedBreakoutStrategy().select(
        trade_date,
        stocks,
        daily_bars,
        hot_stocks,
        stock_daily_basic,
    )

    console.rule(f"确认交易日：{pd.Timestamp(trade_date):%Y-%m-%d}")
    if selected.empty:
        console.print("没有股票满足确认条件")
    else:
        console.print(
            selected[
                [
                    "symbol",
                    "name",
                    "breakout_date",
                    "confirm_date",
                    "breakout_volume_ratio",
                    "confirm_volume_ratio",
                    "confirm_close",
                    "stop_loss_price",
                    "take_profit_price",
                ]
            ]
        )
        console.print(f"共筛选出 {len(selected)} 只股票")
