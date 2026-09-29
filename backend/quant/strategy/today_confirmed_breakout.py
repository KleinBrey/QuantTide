"""放量突破次日确认信号的买卖规则。

入场：确认日收盘价买入，突破日前收盘价止损，按盈亏比设置止盈。

退出（收盘后判断、按收盘价成交、入场当日不退出），按优先级：
1. 止损：收盘价 <= 止损价；
2. 止盈：收盘价 >= 止盈价；
3. 大跌：某日收盘价较前收跌幅大于 5%，次日没有大阳线或中阳线反包则退出；
4. 连续下跌：连续 3 个交易日，每天较前收的跌幅都大于 2%；
5. 放量长上影线：当日成交量 / 前 10 个交易日均成交量 >= 1.5，
   且上影线长度占整根 K 线的比例 >= 40%，
   且下影线长度占整根 K 线的比例 <= 30%，
   且实体长度占整根 K 线的比例 >= 10%。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
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

EXIT_REASON_STOP_LOSS = "stop_loss"
EXIT_REASON_TAKE_PROFIT = "take_profit"
EXIT_REASON_CLOSE_DROP = "close_drop"
EXIT_REASON_DECLINE_STREAK = "decline_streak"
EXIT_REASON_UPPER_SHADOW = "volume_upper_shadow"


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """入场风控与退出规则；不包含任何形态识别参数。"""

    # 止盈距离为每股风险的倍数；2.0 表示目标盈亏比为 2:1。
    risk_reward_ratio: float = 2.0
    # 当日收盘价相对前收的跌幅严格大于该值算“大跌”，次日再决定是否退出。
    previous_close_decline_exit_pct: float = 0.05
    # 大跌次日，大阳线实体相对开盘价的最低涨幅；0.05 表示 5%。
    close_drop_large_bullish_min_body_pct: float = 0.05
    # 大跌次日，反包（当日涨幅与中阳线实体）所需的最低涨幅；0.02 表示 2%。
    close_drop_reversal_min_rise_pct: float = 0.02
    # 触发“连续下跌”退出所需的连续交易日数。
    consecutive_decline_day_count: int = 3
    # 连续下跌期间，每日相对前收的跌幅均须严格大于该值；0.02 表示 2%。
    consecutive_decline_pct: float = 0.02
    # 放量长上影线：当日成交量相对前 N 个交易日均量的最低倍数。
    upper_shadow_volume_ratio_min: float = 1.5
    # 计算均量所用的前序交易日数（不含当日）。
    upper_shadow_volume_lookback: int = 10
    # 上影线占整根 K 线（最高价 - 最低价）的最低比例；0.4 表示 40%。
    upper_shadow_min_pct: float = 0.4
    # 下影线占整根 K 线（最高价 - 最低价）的最高比例；0.3 表示 30%。
    lower_shadow_max_pct: float = 0.3
    # 实体长度占整根 K 线（最高价 - 最低价）的最低比例；0.4 表示 40%。
    candle_body_min_pct: float = 0.1


class TodayConfirmedBreakoutStrategy:
    """组合确认信号，并生成入场、止损、止盈和退出规则。"""

    def __init__(
        self,
        config: StrategyConfig | None = None,
        pattern: TodayConfirmedBreakoutPattern | None = None,
    ) -> None:
        self.config = config or StrategyConfig()
        self.pattern = pattern or TodayConfirmedBreakoutPattern()

    # ------------------------------------------------------------------
    # 入场
    # ------------------------------------------------------------------
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
            trade_date, stocks, daily_bars, hot_stocks, stock_daily_basic
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
            trade_dates, stocks, daily_bars, hot_stocks, stock_daily_basic
        )
        return self._apply_entry_rules(signals)

    def _apply_entry_rules(self, signals: pd.DataFrame) -> pd.DataFrame:
        """确认日收盘入场，突破日前收盘价止损，按盈亏比止盈。"""

        if signals.empty:
            return pd.DataFrame(columns=ENTRY_COLUMNS)

        entries = signals.copy()
        entries["stop_loss_price"] = entries["breakout_prev_close"]
        entries["risk_per_share"] = (
            entries["confirm_close"] - entries["stop_loss_price"]
        )
        # 入场价不高于止损价时，风险为非正，价格关系不成立。
        entries = entries[entries["risk_per_share"] > 0].copy()
        entries["take_profit_price"] = (
            entries["confirm_close"]
            + entries["risk_per_share"] * self.config.risk_reward_ratio
        )
        return entries[ENTRY_COLUMNS].reset_index(drop=True)

    # ------------------------------------------------------------------
    # 退出
    # ------------------------------------------------------------------
    def find_exits(
        self,
        positions: pd.DataFrame,
        daily_bars: pd.DataFrame,
    ) -> pd.DataFrame:
        """为每笔持仓找出首个触发退出规则的交易日。

        positions 需包含 symbol、entry_date、stop_loss_price、take_profit_price。
        daily_bars 需包含 symbol、trade_date、open、high、low、close、volume。
        没有触发退出的持仓不会出现在结果里。
        """

        if positions.empty:
            return pd.DataFrame(columns=EXIT_COLUMNS)

        keys = ["symbol", "entry_date"]
        held = positions[[*keys, "stop_loss_price", "take_profit_price"]].copy()
        held["entry_date"] = pd.to_datetime(held["entry_date"]).dt.normalize()
        held = held.drop_duplicates(keys)

        # 每笔持仓配上它入场之后的每日行情（入场当日不退出，符合 T+1）。
        # 指标在完整历史行情上计算（含入场前），之后再截取入场后的行。
        bars = self._add_daily_columns(self._prepare_bars(daily_bars, held["symbol"]))
        rows = held.merge(bars, on="symbol")
        rows = rows[rows["trade_date"] > rows["entry_date"]].sort_values(
            [*keys, "trade_date"], kind="stable"
        )
        if rows.empty:
            return pd.DataFrame(columns=EXIT_COLUMNS)

        cfg = self.config
        stop_loss = rows["close"] <= rows["stop_loss_price"]
        take_profit = rows["close"] >= rows["take_profit_price"]
        # 前一天大跌，今天没有反包，就退出。
        close_drop = rows["big_drop_yesterday"] & ~self._is_reversal(rows)
        # 最近 N 天涨幅的最大值仍小于 -2%，说明每天都跌超 2%。
        decline_streak = (
            rows.groupby(keys)["rise_pct"].transform(
                lambda s: s.rolling(cfg.consecutive_decline_day_count).max()
            )
            < -cfg.consecutive_decline_pct
        )
        # 放量、上影线足够长、下影线不过长且实体足够大；均量不足 N 天或
        # K 线无振幅时比例为 NaN，整个条件的比较结果为 False。
        upper_shadow = (
            (rows["volume_ratio"] >= cfg.upper_shadow_volume_ratio_min)
            & (rows["upper_shadow_pct"] >= cfg.upper_shadow_min_pct)
            & (rows["lower_shadow_pct"] <= cfg.lower_shadow_max_pct)
            & (rows["candle_body_pct"] >= cfg.candle_body_min_pct)
        )

        # np.select 取第一个成立的条件，所以列表顺序就是优先级。
        rows["exit_reason"] = np.select(
            [stop_loss, take_profit, close_drop, decline_streak, upper_shadow],
            [
                EXIT_REASON_STOP_LOSS,
                EXIT_REASON_TAKE_PROFIT,
                EXIT_REASON_CLOSE_DROP,
                EXIT_REASON_DECLINE_STREAK,
                EXIT_REASON_UPPER_SHADOW,
            ],
            default="",
        )
        exits = (
            rows[rows["exit_reason"] != ""]
            .groupby(keys, sort=False)
            .head(1)
            .rename(columns={"trade_date": "exit_date", "close": "exit_close"})
        )
        return exits[EXIT_COLUMNS].reset_index(drop=True)

    def _is_reversal(self, rows: pd.DataFrame) -> pd.Series:
        """当日是否以大阳线或中阳线反包了前一日的下跌。

        - 大阳线：实体涨幅达到 close_drop_large_bullish_min_body_pct；
        - 中阳线：实体涨幅达到 close_drop_reversal_min_rise_pct，
          且开盘不高于前一日实体下沿、收盘不低于前一日实体上沿（阳包阴）；
        - 两者都要求当日涨幅（相对前收）达到 close_drop_reversal_min_rise_pct。
        实体涨幅为正即代表阳线，所以不用单独判断。
        """

        cfg = self.config
        previous_body_low = np.minimum(rows["previous_open"], rows["previous_close"])
        previous_body_high = np.maximum(rows["previous_open"], rows["previous_close"])

        large_bullish = rows["body_pct"] >= cfg.close_drop_large_bullish_min_body_pct
        medium_engulfing = (
            (rows["body_pct"] >= cfg.close_drop_reversal_min_rise_pct)
            & (rows["open"] <= previous_body_low)
            & (rows["close"] >= previous_body_high)
        )
        enough_rise = rows["rise_pct"] >= cfg.close_drop_reversal_min_rise_pct
        return enough_rise & (large_bullish | medium_engulfing)

    def _add_daily_columns(self, bars: pd.DataFrame) -> pd.DataFrame:
        """计算前收、涨幅、实体涨幅、K 线各部分占比、量比和前一天是否大跌。"""

        by_symbol = bars.groupby("symbol", sort=False)
        bars["previous_open"] = by_symbol["open"].shift(1)
        bars["previous_close"] = by_symbol["close"].shift(1)
        # 四舍五入到 6 位小数，消除浮点误差，让 5%、2% 这类边界值判断准确。
        bars["rise_pct"] = (bars["close"] / bars["previous_close"] - 1).round(6)
        bars["body_pct"] = (bars["close"] / bars["open"] - 1).round(6)

        yesterday_rise = bars.groupby("symbol", sort=False)["rise_pct"].shift(1)
        bars["big_drop_yesterday"] = (
            yesterday_rise < -self.config.previous_close_decline_exit_pct
        )

        # 上影线占比 = (最高价 - 实体上沿) / (最高价 - 最低价)；无振幅时置 NaN。
        candle_range = bars["high"] - bars["low"]
        upper_shadow_len = bars["high"] - np.maximum(bars["open"], bars["close"])
        bars["upper_shadow_pct"] = (
            upper_shadow_len / candle_range.where(candle_range > 0)
        ).round(6)

        # 下影线占比 = (实体下沿 - 最低价) / (最高价 - 最低价)。
        lower_shadow_len = np.minimum(bars["open"], bars["close"]) - bars["low"]
        bars["lower_shadow_pct"] = (
            lower_shadow_len / candle_range.where(candle_range > 0)
        ).round(6)

        # 实体占比 = abs(收盘价 - 开盘价) / (最高价 - 最低价)。
        candle_body_len = (bars["close"] - bars["open"]).abs()
        bars["candle_body_pct"] = (
            candle_body_len / candle_range.where(candle_range > 0)
        ).round(6)

        # 量比 = 当日成交量 / 前 N 个交易日均量（shift(1) 排除当日，凑不满 N 天为 NaN）。
        lookback = self.config.upper_shadow_volume_lookback
        average_volume = by_symbol["volume"].transform(
            lambda s: s.shift(1).rolling(lookback).mean()
        )
        bars["volume_ratio"] = (
            bars["volume"] / average_volume.where(average_volume > 0)
        ).round(6)
        return bars

    @staticmethod
    def _prepare_bars(daily_bars: pd.DataFrame, symbols: pd.Series) -> pd.DataFrame:
        """只保留持仓股票有效的价格与成交量，并按股票、日期排序去重。"""

        bars = daily_bars.loc[
            daily_bars["symbol"].isin(symbols),
            ["symbol", "trade_date", "open", "high", "low", "close", "volume"],
        ].copy()
        bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.normalize()
        for column in ("open", "high", "low", "close", "volume"):
            bars[column] = pd.to_numeric(bars[column], errors="coerce")
        # 缺失（NaN）或非正的价格无法计算涨幅，直接丢弃；
        # 成交量缺失则保留，仅让该日及后续窗口内的量比为 NaN。
        bars = bars[
            (bars["open"] > 0)
            & (bars["high"] > 0)
            & (bars["low"] > 0)
            & (bars["close"] > 0)
        ]
        return (
            bars.sort_values(["symbol", "trade_date"], kind="stable")
            .drop_duplicates(["symbol", "trade_date"], keep="last")
            .reset_index(drop=True)
        )
