"""放量突破次日确认信号的买卖规则。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

from backend.quant.signal.patterns.today_confirmed_breakout import (
    DateLike,
    RESULT_COLUMNS as SIGNAL_COLUMNS,
    TodayConfirmedBreakoutPattern,
)

ENTRY_COLUMNS = [
    *SIGNAL_COLUMNS,
    "stop_loss_price",
    "take_profit_price",
    "risk_per_share",
]
EXIT_COLUMNS = ["symbol", "entry_date", "exit_date", "exit_reason", "exit_close"]

EXIT_REASON_CLOSE_DROP = "close_drop"
EXIT_REASON_DECLINE_STREAK = "decline_streak"


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """入场风控与退出规则；不包含任何形态识别参数。"""

    # 止盈距离为每股风险的倍数；2.0 表示目标盈亏比为 2:1。
    risk_reward_ratio: float = 2.0
    # 当日收盘价相对前收的跌幅严格大于该值时退出；0.05 表示 5%。
    previous_close_decline_exit_pct: float = 0.05
    # 触发“连续下跌”退出所需的连续交易日数。
    consecutive_decline_day_count: int = 3
    # 连续下跌期间，每日相对前收的跌幅均须严格大于该值；0.02 表示 2%。
    consecutive_decline_pct: float = 0.02

    def __post_init__(self) -> None:
        if self.risk_reward_ratio <= 0:
            raise ValueError("risk_reward_ratio 必须大于 0")
        if self.previous_close_decline_exit_pct < 0:
            raise ValueError("previous_close_decline_exit_pct 不能为负数")
        if self.consecutive_decline_day_count <= 0:
            raise ValueError("consecutive_decline_day_count 必须大于 0")
        if self.consecutive_decline_pct < 0:
            raise ValueError("consecutive_decline_pct 不能为负数")


class TodayConfirmedBreakoutStrategy:
    """组合确认信号，并生成入场、止损、止盈和退出规则。"""

    def __init__(
        self,
        config: StrategyConfig | None = None,
        pattern: TodayConfirmedBreakoutPattern | None = None,
    ) -> None:
        self.config = config or StrategyConfig()
        self.pattern = pattern or TodayConfirmedBreakoutPattern()

    def generate_entries(
        self,
        trade_date: DateLike,
        stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        hot_stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """为一个交易日生成包含风控价格的入场候选。"""

        signals = self.pattern.scan(
            trade_date,
            stocks,
            daily_bars,
            hot_stocks,
            stock_daily_basic,
        )
        return self._apply_entry_rules(signals)

    def generate_entries_range(
        self,
        trade_dates: Iterable[DateLike],
        stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        hot_stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """为多个交易日生成包含风控价格的入场候选。"""

        signals = self.pattern.scan_range(
            trade_dates,
            stocks,
            daily_bars,
            hot_stocks,
            stock_daily_basic,
        )
        return self._apply_entry_rules(signals)

    def _apply_entry_rules(self, signals: pd.DataFrame) -> pd.DataFrame:
        """把信号转换为可执行候选：确认日收盘入场，突破日前收盘止损。"""

        if signals.empty:
            return pd.DataFrame(columns=ENTRY_COLUMNS)

        entries = signals.copy()
        entries["stop_loss_price"] = entries["breakout_prev_close"]
        entries["risk_per_share"] = (
            entries["confirm_close"] - entries["stop_loss_price"]
        )
        entries = entries[entries["risk_per_share"] > 0].copy()
        entries["take_profit_price"] = (
            entries["confirm_close"]
            + entries["risk_per_share"] * self.config.risk_reward_ratio
        )
        return entries[ENTRY_COLUMNS].reset_index(drop=True)

    def find_exits(
        self,
        positions: pd.DataFrame,
        daily_bars: pd.DataFrame,
    ) -> pd.DataFrame:
        """为每笔持仓找出首个触发策略退出规则的交易日。"""

        if positions.empty or daily_bars.empty:
            return pd.DataFrame(columns=EXIT_COLUMNS)

        held = positions[["symbol", "entry_date"]].copy()
        held["entry_date"] = pd.to_datetime(held["entry_date"]).dt.normalize()
        held = held.drop_duplicates()

        bars = self._prepare_bars(daily_bars, held["symbol"])
        if bars.empty:
            return pd.DataFrame(columns=EXIT_COLUMNS)

        grouped = bars.groupby("symbol", sort=False, observed=True)
        bars["daily_decline_pct"] = 1 - bars["close"] / grouped["close"].shift(1)

        keys = ["symbol", "entry_date"]
        rows = held.merge(
            bars[["symbol", "trade_date", "close", "daily_decline_pct"]],
            on="symbol",
            how="inner",
        )
        rows = rows[rows["trade_date"] > rows["entry_date"]].sort_values(
            [*keys, "trade_date"], kind="stable"
        )
        if rows.empty:
            return pd.DataFrame(columns=EXIT_COLUMNS)

        close_drop = (
            rows["daily_decline_pct"]
            > self.config.previous_close_decline_exit_pct
        )
        weakest_decline = (
            rows.groupby(keys, sort=False)["daily_decline_pct"]
            .rolling(
                self.config.consecutive_decline_day_count,
                min_periods=self.config.consecutive_decline_day_count,
            )
            .min()
            .reset_index(level=[0, 1], drop=True)
        )
        decline_streak = weakest_decline > self.config.consecutive_decline_pct

        rows["exit_reason"] = None
        rows.loc[decline_streak, "exit_reason"] = EXIT_REASON_DECLINE_STREAK
        rows.loc[close_drop, "exit_reason"] = EXIT_REASON_CLOSE_DROP

        exits = (
            rows[rows["exit_reason"].notna()]
            .groupby(keys, sort=False)
            .head(1)
            .rename(columns={"trade_date": "exit_date", "close": "exit_close"})
        )
        return exits[EXIT_COLUMNS].reset_index(drop=True)

    def next_decline_streak(
        self,
        *,
        close_price: float,
        previous_close: float,
        current_streak: int,
    ) -> int:
        """按策略的连续下跌定义更新计数。"""

        decline_pct = 1 - close_price / previous_close
        return (
            current_streak + 1
            if decline_pct > self.config.consecutive_decline_pct
            else 0
        )

    def exit_reason(
        self,
        *,
        close_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        previous_close: float,
        consecutive_decline_count: int,
    ) -> str | None:
        """按优先级判断单日退出原因。"""

        risk_reason = self.risk_exit_reason(
            close_price=close_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )
        if risk_reason is not None:
            return risk_reason
        decline_pct = 1 - close_price / previous_close
        if decline_pct > self.config.previous_close_decline_exit_pct:
            return EXIT_REASON_CLOSE_DROP
        if consecutive_decline_count >= self.config.consecutive_decline_day_count:
            return EXIT_REASON_DECLINE_STREAK
        return None

    @staticmethod
    def risk_exit_reason(
        *,
        close_price: float,
        stop_loss_price: float,
        take_profit_price: float,
    ) -> str | None:
        """判断止损和止盈规则。"""

        if close_price <= stop_loss_price:
            return "stop_loss"
        if close_price >= take_profit_price:
            return "take_profit"
        return None

    @staticmethod
    def _prepare_bars(
        daily_bars: pd.DataFrame,
        symbols: pd.Series,
    ) -> pd.DataFrame:
        """清洗退出规则所需的收盘行情。"""

        bars = daily_bars[daily_bars["symbol"].isin(symbols)].copy()
        bars["trade_date"] = pd.to_datetime(
            bars["trade_date"], errors="coerce"
        ).dt.normalize()
        bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
        bars = bars.dropna(subset=["symbol", "trade_date", "close"])
        bars = bars[bars["close"] > 0]
        return (
            bars.sort_values(["symbol", "trade_date"], kind="stable")
            .drop_duplicates(["symbol", "trade_date"], keep="last")
            .reset_index(drop=True)
        )
