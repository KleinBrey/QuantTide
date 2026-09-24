"""识别前一交易日放量突破、当前交易日小阳线确认形态。

信号分为两个阶段：

1. 突破日（确认日之前最近一个全市场交易日）：放量、收涨、短期涨幅有限、
   20 日线在 10 日线之上、离 20 日低点不远；
2. 确认日：小阳线、影线受控、量能保持。

`scan`（单日）与 `scan_range`（多日）共用同一条向量化流水线。
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Union

import pandas as pd
from rich.console import Console

from backend.app.database import DuckDBDatabase
from backend.app.repository import (
    DailyBarRepository,
    StockDailyBasicRepository,
    StockHotDailyRepository,
    StockRepository,
)
from backend.quant.stock import filter_market_cap, filter_static_stocks

console = Console()

DateLike = Union[date, str, pd.Timestamp]

# 形态识别最终向信号 API 暴露的字段，不包含买卖规则。
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
    "breakout_prev_close",
    "hot_rank",
    "hot_value",
    "selection_rank",
]

# 突破日需要从行情表带出的列。
_BREAKOUT_SOURCE_COLUMNS = [
    "symbol",
    "trade_date",
    "close",
    "volume",
    "breakout_prev_close",
    "breakout_previous_avg_volume",
    "breakout_volume_ratio",
    "breakout_return_1d_pct",
    "breakout_return_5d_pct",
    "breakout_from_low",
    "breakout_ma_short",
    "breakout_ma_long",
]


@dataclass(frozen=True, slots=True)
class SignalConfig:
    """信号识别参数。比例一律用小数表示，0.03 代表 3%。"""

    # ---- 突破日条件 ----
    # 总市值必须大于该值（元）。
    min_market_cap: float = 10_000_000_000
    # 用突破日之前的 N 个交易日计算基准均量（不含突破日）。
    previous_volume_days: int = 20
    # 突破日成交量 / 基准均量 至少达到该倍数。
    min_breakout_volume_ratio: float = 1.5
    # 突破日涨幅必须大于该值（0 即收涨）。
    min_breakout_return_1d_pct: float = 0.0
    # 近 N 个交易日累计涨幅必须严格小于该值。
    weekly_return_days: int = 5
    max_breakout_return_5d_pct: float = 0.10
    # 突破日收盘价相较于过去 N 日最低收盘价的涨幅上限。
    low_window_days: int = 20
    max_breakout_from_low: float = 0.10
    # 收盘价均线窗口；突破日要求长期均线严格大于短期均线。
    short_ma_days: int = 10
    long_ma_days: int = 20

    # ---- 确认日条件 ----
    # 确认日涨幅（相对突破日收盘价）需在 (min, max] 区间内。
    min_confirm_return_1d_pct: float = 0.0
    max_confirm_return_1d_pct: float = 0.05
    # 下 / 上影线占整根 K 线振幅的比例上限。
    max_confirm_lower_wick_ratio: float = 0.6
    max_confirm_upper_wick_ratio: float = 0.4
    # 确认日成交量至少保留突破日成交量的比例。
    min_confirm_volume_ratio: float = 0.70
    @property
    def warmup_days(self) -> int:
        """计算一个突破信号所需的最少历史交易日数量。"""

        return max(
            self.previous_volume_days + 1,
            self.short_ma_days,
            self.long_ma_days,
            self.low_window_days,
            self.weekly_return_days + 1,
        )


def _empty_result() -> pd.DataFrame:
    return pd.DataFrame(columns=RESULT_COLUMNS)


class TodayConfirmedBreakoutPattern:
    """先找前一交易日突破股，再用确认日 K 线识别确认信号。"""

    def __init__(self, config: SignalConfig | None = None) -> None:
        self.config = config or SignalConfig()

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------
    def scan(
        self,
        trade_date: DateLike,
        stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        hot_stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """返回在 trade_date 当天通过二次确认的股票。"""

        # 实盘/命令行通常只有“最新”市值快照，允许在没有历史匹配时回退到最新值；
        # 历史扫描（scan_range）默认不回退，避免使用未来市值。
        return self.scan_range(
            [trade_date],
            stocks,
            daily_bars,
            hot_stocks,
            stock_daily_basic,
            latest_market_cap_fallback=True,
        )

    def scan_range(
        self,
        trade_dates: Iterable[DateLike],
        stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        hot_stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
        *,
        latest_market_cap_fallback: bool = False,
    ) -> pd.DataFrame:
        """一次计算多个确认日的信号，避免逐日重复扫描行情。"""

        confirm_dates = self._normalize_dates(trade_dates)
        if confirm_dates.empty or stocks.empty or daily_bars.empty:
            return _empty_result()

        eligible = filter_static_stocks(stocks)
        if eligible.empty:
            return _empty_result()

        # 1. 日期配对：每个确认日只能使用它之前最近一个全市场交易日作为突破日。
        bars = self._normalize_bars(daily_bars)
        date_pairs, market_dates = self._pair_dates(bars, confirm_dates)
        if date_pairs.empty:
            return _empty_result()

        # 2. 清洗行情并只保留必要的时间窗口（突破日往前留出指标预热期）。
        bars = self._clean_bars(bars, eligible["symbol"])
        bars = self._trim_bars(bars, market_dates, date_pairs, confirm_dates.max())
        if bars.empty:
            return _empty_result()

        # 3. 突破阶段：滚动指标 + 条件过滤。
        bars = self._add_breakout_indicators(bars)
        signals = self._select_breakout_signals(bars, date_pairs)
        if signals.empty:
            return _empty_result()

        # 4. 确认阶段：拼接确认日 K 线，检查形态并计算止盈止损。
        signals = self._attach_confirm_bars(signals, bars, confirm_dates)
        signals = self._apply_confirmation(signals)
        if signals.empty:
            return _empty_result()

        # 5. 基本面与热度：放在最后，只处理已通过量价形态的少量信号。
        signals = signals.merge(
            eligible[["symbol", "name", "exchange"]],
            on="symbol",
            how="inner",
            sort=False,
        )
        signals = self._merge_market_cap(
            signals,
            stock_daily_basic,
            fallback_to_latest=latest_market_cap_fallback,
        )
        signals = filter_market_cap(self.config.min_market_cap, signals)
        if signals.empty:
            return _empty_result()

        signals = self._merge_heat(signals, hot_stocks)
        signals = signals.sort_values(
            ["confirm_date", "hot_rank", "breakout_volume_ratio"],
            ascending=[True, True, False],
            na_position="last",
            kind="stable",
        )
        signals["selection_rank"] = (
            signals.groupby("confirm_date", sort=False).cumcount() + 1
        )
        return signals[RESULT_COLUMNS].reset_index(drop=True)

    # ------------------------------------------------------------------
    # 行情准备
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_dates(trade_dates: Iterable[DateLike]) -> pd.DatetimeIndex:
        dates = pd.DatetimeIndex(
            pd.to_datetime(list(trade_dates), errors="raise")
        ).normalize()
        return dates.drop_duplicates().sort_values()

    @staticmethod
    def _normalize_bars(daily_bars: pd.DataFrame) -> pd.DataFrame:
        """统一日期到零点，避免带时分秒的输入无法与日频数据匹配。"""

        bars = daily_bars.copy()
        bars["trade_date"] = pd.to_datetime(
            bars["trade_date"], errors="coerce"
        ).dt.normalize()
        return bars

    @staticmethod
    def _pair_dates(
        bars: pd.DataFrame,
        confirm_dates: pd.DatetimeIndex,
    ) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
        """为每个确认日找到其之前最近的全市场交易日作为突破日。"""

        market_dates = pd.DatetimeIndex(
            bars["trade_date"].dropna().drop_duplicates().sort_values()
        )
        previous = market_dates.searchsorted(confirm_dates, side="left") - 1
        valid = previous >= 0
        pairs = pd.DataFrame(
            {
                "confirm_date": confirm_dates[valid],
                "breakout_date": market_dates[previous[valid]],
            }
        )
        return pairs, market_dates

    @staticmethod
    def _clean_bars(bars: pd.DataFrame, symbols: pd.Series) -> pd.DataFrame:
        """只保留候选股票的有效行情，并按股票、日期排序去重。"""

        # 先按股票池裁剪，再做类型转换，降低批量计算开销。
        bars = bars[bars["symbol"].isin(symbols)].copy()
        for column in ("open", "high", "low", "close", "volume"):
            bars[column] = pd.to_numeric(bars[column], errors="coerce")
        bars = bars.dropna(subset=["trade_date", "close", "volume"])
        # 零值和负值无法用于收益率、量比计算。
        bars = bars[(bars["close"] > 0) & (bars["volume"] > 0)]
        return (
            bars.sort_values(["symbol", "trade_date"], kind="stable")
            .drop_duplicates(["symbol", "trade_date"], keep="last")
            .reset_index(drop=True)
        )

    def _trim_bars(
        self,
        bars: pd.DataFrame,
        market_dates: pd.DatetimeIndex,
        date_pairs: pd.DataFrame,
        last_confirm_date: pd.Timestamp,
    ) -> pd.DataFrame:
        """丢弃用不到的行情：最后确认日之后（防未来数据）与预热期之前。

        预热期按全市场交易日的 2 倍窗口留余量，覆盖个股停牌导致的行数缺口。
        """

        first_position = market_dates.searchsorted(date_pairs["breakout_date"].min())
        start_position = max(0, first_position - self.config.warmup_days * 2)
        start_date = market_dates[start_position]
        return bars[
            (bars["trade_date"] >= start_date)
            & (bars["trade_date"] <= last_confirm_date)
        ].reset_index(drop=True)

    # ------------------------------------------------------------------
    # 突破阶段
    # ------------------------------------------------------------------
    @staticmethod
    def _rolling(grouped_series, window: int, func: str) -> pd.Series:
        """按股票滚动统计，窗口不满则为 NaN，结果与原行索引对齐。"""

        rolled = grouped_series.rolling(window, min_periods=window)
        return getattr(rolled, func)().reset_index(level=0, drop=True)

    def _add_breakout_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        """为每一行计算“若以该日为突破日”的全部指标（向量化，无逐股循环）。"""

        cfg = self.config
        grouped = bars.groupby("symbol", sort=False, observed=True)
        close_group = grouped["close"]

        previous_close = close_group.shift(1)
        # 基准均量取该日之前 N 日（不含当日）。
        avg_volume = self._rolling(grouped["volume"], cfg.previous_volume_days, "mean")
        previous_avg_volume = avg_volume.groupby(
            bars["symbol"], sort=False, observed=True
        ).shift(1)
        low = self._rolling(close_group, cfg.low_window_days, "min")

        bars["breakout_prev_close"] = previous_close
        bars["breakout_previous_avg_volume"] = previous_avg_volume
        bars["breakout_volume_ratio"] = bars["volume"] / previous_avg_volume
        bars["breakout_return_1d_pct"] = bars["close"] / previous_close - 1
        bars["breakout_return_5d_pct"] = (
            bars["close"] / close_group.shift(cfg.weekly_return_days) - 1
        )
        bars["breakout_from_low"] = bars["close"] / low - 1
        bars["breakout_ma_short"] = self._rolling(
            close_group, cfg.short_ma_days, "mean"
        )
        bars["breakout_ma_long"] = self._rolling(close_group, cfg.long_ma_days, "mean")
        return bars

    def _select_breakout_signals(
        self,
        bars: pd.DataFrame,
        date_pairs: pd.DataFrame,
    ) -> pd.DataFrame:
        """在突破日行上应用全部突破条件，并与确认日配对。"""

        cfg = self.config
        mask = (
            bars["trade_date"].isin(date_pairs["breakout_date"])
            & (bars["breakout_volume_ratio"] >= cfg.min_breakout_volume_ratio)
            & (bars["breakout_return_1d_pct"] > cfg.min_breakout_return_1d_pct)
            & (bars["breakout_return_5d_pct"] < cfg.max_breakout_return_5d_pct)
            & (bars["breakout_ma_long"] > bars["breakout_ma_short"])
            & (bars["breakout_from_low"] <= cfg.max_breakout_from_low)
        )
        signals = bars.loc[mask, _BREAKOUT_SOURCE_COLUMNS].rename(
            columns={
                "trade_date": "breakout_date",
                "close": "breakout_close",
                "volume": "breakout_volume",
            }
        )
        return date_pairs.merge(signals, on="breakout_date", how="inner", sort=False)

    # ------------------------------------------------------------------
    # 确认阶段
    # ------------------------------------------------------------------
    @staticmethod
    def _attach_confirm_bars(
        signals: pd.DataFrame,
        bars: pd.DataFrame,
        confirm_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """拼接确认日 K 线；确认日停牌/无行情的股票被 inner join 剔除。"""

        confirm_bars = bars.loc[
            bars["trade_date"].isin(confirm_dates),
            ["symbol", "trade_date", "open", "high", "low", "close", "volume"],
        ].rename(
            columns={
                "trade_date": "confirm_date",
                "open": "confirm_open",
                "high": "confirm_high",
                "low": "confirm_low",
                "close": "confirm_close",
                "volume": "confirm_volume",
            }
        )
        return signals.merge(
            confirm_bars, on=["confirm_date", "symbol"], how="inner", sort=False
        )

    def _apply_confirmation(self, rows: pd.DataFrame) -> pd.DataFrame:
        """检查小阳线、影线与量能。"""

        cfg = self.config
        # 振幅是两个影线比例的分母；非正振幅置为 NaN，使后续比较自然为 False。
        candle_range = (rows["confirm_high"] - rows["confirm_low"]).where(
            lambda s: s > 0
        )

        # 确认日涨幅按前一交易日（突破日）收盘价计算，不能只看日内实体。
        confirm_return = rows["confirm_close"] / rows["breakout_close"] - 1
        rows = rows.assign(
            confirm_body_pct=rows["confirm_close"] / rows["confirm_open"] - 1,
            # 只接受阳线：开盘价是实体下沿、收盘价是实体上沿。
            confirm_lower_wick_ratio=(rows["confirm_open"] - rows["confirm_low"])
            / candle_range,
            confirm_upper_wick_ratio=(rows["confirm_high"] - rows["confirm_close"])
            / candle_range,
            confirm_volume_ratio=rows["confirm_volume"] / rows["breakout_volume"],
        )
        mask = (
            (rows["confirm_close"] > rows["confirm_open"])
            & (confirm_return > cfg.min_confirm_return_1d_pct)
            & (confirm_return <= cfg.max_confirm_return_1d_pct)
            & (rows["confirm_lower_wick_ratio"] <= cfg.max_confirm_lower_wick_ratio)
            & (rows["confirm_upper_wick_ratio"] <= cfg.max_confirm_upper_wick_ratio)
            & (rows["confirm_volume_ratio"] >= cfg.min_confirm_volume_ratio)
        )
        return rows[mask].copy()

    # ------------------------------------------------------------------
    # 市值与热度
    # ------------------------------------------------------------------
    @staticmethod
    def _merge_market_cap(
        candidates: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
        *,
        fallback_to_latest: bool = False,
    ) -> pd.DataFrame:
        """按确认日向前匹配每只股票最近可用的历史市值（point-in-time）。

        fallback_to_latest=True 时，匹配不到的股票使用其最新市值，仅适用于实盘。
        """

        candidates = candidates.copy()
        candidates["symbol"] = candidates["symbol"].astype("string")
        candidates["market_cap"] = pd.Series(
            pd.NA, index=candidates.index, dtype="Float64"
        )

        required = {"symbol", "trade_date", "market_cap"}
        if stock_daily_basic.empty or not required.issubset(stock_daily_basic.columns):
            return candidates

        history = stock_daily_basic[["symbol", "trade_date", "market_cap"]].copy()
        history["symbol"] = history["symbol"].astype("string")
        history["trade_date"] = pd.to_datetime(
            history["trade_date"], errors="coerce"
        ).dt.normalize()
        history["market_cap"] = pd.to_numeric(history["market_cap"], errors="coerce")
        history = (
            history.dropna(subset=["symbol", "trade_date", "market_cap"])
            .drop_duplicates(["symbol", "trade_date"], keep="last")
            .sort_values("trade_date")
        )
        if history.empty:
            return candidates

        merged = pd.merge_asof(
            candidates.drop(columns="market_cap").sort_values("confirm_date"),
            history,
            left_on="confirm_date",
            right_on="trade_date",
            by="symbol",
            direction="backward",
        ).drop(columns="trade_date")

        if fallback_to_latest:
            latest = history.groupby("symbol")["market_cap"].last()
            merged["market_cap"] = merged["market_cap"].fillna(
                merged["symbol"].map(latest)
            )
        return merged.reset_index(drop=True)

    @staticmethod
    def _merge_heat(result: pd.DataFrame, hot_stocks: pd.DataFrame) -> pd.DataFrame:
        """补充热度排名。

        热度表行序即排名：含 trade_date 时按突破日逐日排名，否则视为最新快照。
        同一股票（同一日）只取第一条；没有热度的信号排在有热度者之后。
        """

        result = result.copy()
        if hot_stocks.empty:
            result["hot_rank"] = pd.NA
            result["hot_value"] = pd.NA
            return result

        heat = hot_stocks.copy()
        if "trade_date" not in heat.columns:
            heat = heat.drop_duplicates("symbol").reset_index(drop=True)
            heat["hot_rank"] = heat.index + 1
            return result.merge(
                heat[["symbol", "hot_rank", "hot_value"]],
                on="symbol",
                how="left",
                sort=False,
            )

        heat["trade_date"] = pd.to_datetime(
            heat["trade_date"], errors="coerce"
        ).dt.normalize()
        heat = heat.drop_duplicates(["trade_date", "symbol"]).copy()
        heat["hot_rank"] = heat.groupby("trade_date", sort=False).cumcount() + 1
        heat = heat.rename(columns={"trade_date": "breakout_date"})
        return result.merge(
            heat[["breakout_date", "symbol", "hot_rank", "hot_value"]],
            on=["breakout_date", "symbol"],
            how="left",
            sort=False,
        )


def load_market_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """读取本地 A 股数据。"""

    database = DuckDBDatabase()
    return (
        StockRepository(database).get_table_data(),
        DailyBarRepository(database).get_table_data(),
        StockHotDailyRepository(database).get_latest(),
        StockDailyBasicRepository(database).get_latest_data(),
    )


def run_signal(
    *,
    stocks: pd.DataFrame,
    daily_bars: pd.DataFrame,
    hot_stocks: pd.DataFrame,
    stock_daily_basic: pd.DataFrame,
    trade_date: DateLike | None = None,
) -> pd.DataFrame:
    """识别放量突破次日确认信号；未指定日期时使用最新交易日。"""

    trade_date = trade_date or pd.to_datetime(daily_bars["trade_date"]).max()
    return TodayConfirmedBreakoutPattern().scan(
        trade_date,
        stocks,
        daily_bars,
        hot_stocks,
        stock_daily_basic,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="识别放量突破次日确认信号")
    parser.add_argument("--trade-date", help="确认日期，例如 2025-09-11")
    args = parser.parse_args()

    stocks, daily_bars, hot_stocks, stock_daily_basic = load_market_data()
    selected = run_signal(
        stocks=stocks,
        daily_bars=daily_bars,
        hot_stocks=hot_stocks,
        stock_daily_basic=stock_daily_basic,
        trade_date=args.trade_date,
    )
    trade_date = args.trade_date or pd.to_datetime(daily_bars["trade_date"]).max()

    console.rule(f"确认交易日：{pd.Timestamp(trade_date):%Y-%m-%d}")
    if selected.empty:
        console.print("没有股票满足确认形态")
        return

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
            ]
        ]
    )
    console.print(f"共识别出 {len(selected)} 个信号")


if __name__ == "__main__":
    main()
