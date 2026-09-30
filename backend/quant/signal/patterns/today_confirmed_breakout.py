"""识别前一交易日放量突破、当前交易日确认跟随。

信号分为两个阶段：

1. 突破日：
总市值大于100亿,ST股除外,科创板除外,北交所除外;
当日涨幅大于0;
当日成交量 / 前20个交易日均成交量 >= 1.5;
最近5个交易日涨幅小于10%;
距离最近20个交易日最低点涨幅小于10%;
20日线大于10日线;

2. 确认日：
当日涨幅在0% ~ 5% 之间;
上影线长度<=整个体积的40%;
下影线长度<=整个体积的300%(几乎等于不用管);
成交量不小于突破日的70%

按现在个股热度排序

`scan`（单日）与 `scan_range`（多日）共用同一条向量化流水线。
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
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
from backend.quant.factor import calculate_volume_ratio
from backend.quant.stock import filter_market_cap, filter_static_stocks

console = Console()

DateLike = date | str | pd.Timestamp

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
    "selection_rank",
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
    max_confirm_lower_wick_ratio: float = 3
    max_confirm_upper_wick_ratio: float = 0.4
    # 确认日成交量至少保留突破日成交量的比例。
    min_confirm_volume_ratio: float = 0.70

    @property
    def warmup_days(self) -> int:
        """算出一个突破信号所需的最少历史交易日数量。"""

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

        # 实盘/命令行通常只有“最新”市值快照，匹配不到历史市值时允许回退到最新值；
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

        # 1. 行情准备：确认日配突破日，清洗行情，只留用得到的时间段。
        date_pairs = self._pair_dates(daily_bars, confirm_dates)
        bars = self._prepare_bars(daily_bars, eligible["symbol"])
        bars = self._trim_bars(bars, date_pairs, confirm_dates.max())

        # 2. 突破阶段：计算指标并筛选突破日。
        bars = self._add_breakout_indicators(bars)
        signals = self._select_breakout_signals(bars, date_pairs)

        # 3. 确认阶段：拼上确认日 K 线，检查形态。
        signals = self._attach_confirm_bars(signals, bars, confirm_dates)
        signals = self._apply_confirmation(signals)
        if signals.empty:
            return _empty_result()

        # 4. 补充基本面与热度，最后排名。只处理已通过形态的少量信号。
        signals = signals.merge(eligible[["symbol", "name", "exchange"]], on="symbol")
        signals = self._merge_market_cap(
            signals, stock_daily_basic, fallback_to_latest=latest_market_cap_fallback
        )
        signals = filter_market_cap(self.config.min_market_cap, signals)
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
        """统一到零点，去重并排序。"""

        dates = pd.DatetimeIndex(pd.to_datetime(list(trade_dates))).normalize()
        return dates.drop_duplicates().sort_values()

    @staticmethod
    def _pair_dates(
        daily_bars: pd.DataFrame,
        confirm_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """每个确认日配上它之前最近的一个全市场交易日，作为突破日。"""

        market_dates = pd.DatetimeIndex(
            pd.to_datetime(daily_bars["trade_date"]).dt.normalize().unique()
        ).sort_values()
        previous = market_dates.searchsorted(confirm_dates, side="left") - 1
        has_previous = previous >= 0
        return pd.DataFrame(
            {
                "confirm_date": confirm_dates[has_previous],
                "breakout_date": market_dates[previous[has_previous]],
            }
        )

    @staticmethod
    def _prepare_bars(daily_bars: pd.DataFrame, symbols: pd.Series) -> pd.DataFrame:
        """只保留候选股票的有效行情，并按股票、日期排序去重。"""

        # 先按股票池裁剪，再做类型转换，降低批量计算开销。
        columns = ["symbol", "trade_date", "open", "high", "low", "close", "volume"]
        bars = daily_bars.loc[daily_bars["symbol"].isin(symbols), columns].copy()
        bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.normalize()
        for column in ("open", "high", "low", "close", "volume"):
            bars[column] = pd.to_numeric(bars[column], errors="coerce")
        # 缺失、零值和负值无法用于收益率、量比计算（缺失值比较结果为 False）。
        bars = bars[(bars["close"] > 0) & (bars["volume"] > 0)]
        return (
            bars.sort_values(["symbol", "trade_date"], kind="stable")
            .drop_duplicates(["symbol", "trade_date"], keep="last")
            .reset_index(drop=True)
        )

    def _trim_bars(
        self,
        bars: pd.DataFrame,
        date_pairs: pd.DataFrame,
        last_confirm_date: pd.Timestamp,
    ) -> pd.DataFrame:
        """丢弃用不到的行情：最后确认日之后，以及首个突破日之前的多余历史。"""

        # 1 个交易日约 1.4 个自然日，这里放大到 3 倍，给周末、节假日和停牌留足余量。
        start_date = date_pairs["breakout_date"].min() - pd.Timedelta(
            days=self.config.warmup_days * 3
        )
        return bars[
            (bars["trade_date"] >= start_date)
            & (bars["trade_date"] <= last_confirm_date)
        ].reset_index(drop=True)

    # ------------------------------------------------------------------
    # 突破阶段
    # ------------------------------------------------------------------
    def _add_breakout_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        """为每一行计算“如果以这一天作为突破日”的各项指标。"""

        cfg = self.config
        by_symbol = bars.groupby("symbol")
        close = by_symbol["close"]

        # 滚动结果带有“股票”这一层索引，droplevel(0) 去掉后即可与原行对齐。
        bars["breakout_prev_close"] = close.shift(1)
        # recent_days=1 表示以当日成交量对比此前 N 日的基准均量。
        bars["breakout_volume_ratio"] = by_symbol["volume"].transform(
            lambda volume: calculate_volume_ratio(
                volume.to_frame(name="volume"),
                recent_days=1,
                previous_days=cfg.previous_volume_days,
            )["volume_ratio"]
        )
        bars["breakout_return_1d_pct"] = bars["close"] / bars["breakout_prev_close"] - 1
        bars["breakout_return_5d_pct"] = (
            bars["close"] / close.shift(cfg.weekly_return_days) - 1
        )
        lowest_close = close.rolling(cfg.low_window_days).min().droplevel(0)
        bars["breakout_from_low"] = bars["close"] / lowest_close - 1
        bars["breakout_ma_short"] = close.rolling(cfg.short_ma_days).mean().droplevel(0)
        bars["breakout_ma_long"] = close.rolling(cfg.long_ma_days).mean().droplevel(0)
        return bars

    def _select_breakout_signals(
        self,
        bars: pd.DataFrame,
        date_pairs: pd.DataFrame,
    ) -> pd.DataFrame:
        """在突破日那一行上检查全部突破条件，并配上对应的确认日。"""

        cfg = self.config
        is_breakout = (
            bars["trade_date"].isin(date_pairs["breakout_date"])
            & (bars["breakout_volume_ratio"] >= cfg.min_breakout_volume_ratio)
            & (bars["breakout_return_1d_pct"] > cfg.min_breakout_return_1d_pct)
            & (bars["breakout_return_5d_pct"] < cfg.max_breakout_return_5d_pct)
            & (bars["breakout_ma_long"] > bars["breakout_ma_short"])
            & (bars["breakout_from_low"] <= cfg.max_breakout_from_low)
        )
        signals = bars.loc[
            is_breakout,
            [
                "symbol",
                "trade_date",
                "close",
                "volume",
                "breakout_prev_close",
                "breakout_volume_ratio",
                "breakout_return_1d_pct",
            ],
        ].rename(
            columns={
                "trade_date": "breakout_date",
                "close": "breakout_close",
                "volume": "breakout_volume",
            }
        )
        return date_pairs.merge(signals, on="breakout_date")

    # ------------------------------------------------------------------
    # 确认阶段
    # ------------------------------------------------------------------
    @staticmethod
    def _attach_confirm_bars(
        signals: pd.DataFrame,
        bars: pd.DataFrame,
        confirm_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """拼接确认日 K 线；确认日停牌、没有行情的股票会被剔除。"""

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
        return signals.merge(confirm_bars, on=["confirm_date", "symbol"])

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
        is_confirmed = (
            (rows["confirm_close"] > rows["confirm_open"])
            & (confirm_return > cfg.min_confirm_return_1d_pct)
            & (confirm_return <= cfg.max_confirm_return_1d_pct)
            & (rows["confirm_lower_wick_ratio"] <= cfg.max_confirm_lower_wick_ratio)
            & (rows["confirm_upper_wick_ratio"] <= cfg.max_confirm_upper_wick_ratio)
            & (rows["confirm_volume_ratio"] >= cfg.min_confirm_volume_ratio)
        )
        return rows[is_confirmed]

    # ------------------------------------------------------------------
    # 市值与热度
    # ------------------------------------------------------------------
    @staticmethod
    def _merge_market_cap(
        signals: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
        *,
        fallback_to_latest: bool,
    ) -> pd.DataFrame:
        """按确认日向前匹配每只股票最近一次的历史市值，避免使用未来市值。

        fallback_to_latest=True 时，匹配不到的股票改用其最新市值，仅适用于实盘。
        """

        history = stock_daily_basic[["symbol", "trade_date", "market_cap"]].copy()
        history["trade_date"] = pd.to_datetime(history["trade_date"]).dt.normalize()
        history["market_cap"] = pd.to_numeric(history["market_cap"], errors="coerce")
        history = history.dropna().sort_values("trade_date")

        signals = pd.merge_asof(
            signals.sort_values("confirm_date"),
            history,
            left_on="confirm_date",
            right_on="trade_date",
            by="symbol",
            direction="backward",
        ).drop(columns="trade_date")

        if fallback_to_latest:
            latest = history.groupby("symbol")["market_cap"].last()
            signals["market_cap"] = signals["market_cap"].fillna(
                signals["symbol"].map(latest)
            )
        return signals

    @staticmethod
    def _merge_heat(signals: pd.DataFrame, hot_stocks: pd.DataFrame) -> pd.DataFrame:
        """补充热度排名；直接使用热度表存储的排名，没有热度的信号排在有热度者之后。"""

        heat = hot_stocks.copy()
        if "trade_date" in heat.columns:
            # 历史热度：每个突破日各有一份排名。
            heat["breakout_date"] = pd.to_datetime(heat["trade_date"]).dt.normalize()
            keys = ["breakout_date", "symbol"]
            heat = heat.drop_duplicates(keys)
            heat["hot_rank"] = heat["rank"]
        else:
            # 最新热度快照：整体一份排名。
            keys = ["symbol"]
            heat = heat.drop_duplicates(keys)
            heat["hot_rank"] = heat["rank"]
        return signals.merge(
            heat[[*keys, "hot_rank"]], on=keys, how="left"
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
        trade_date, stocks, daily_bars, hot_stocks, stock_daily_basic
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="识别放量突破次日确认信号")
    parser.add_argument("--trade-date", help="确认日期，例如 2025-09-11")
    args = parser.parse_args()

    stocks, daily_bars, hot_stocks, stock_daily_basic = load_market_data()
    trade_date = args.trade_date or pd.to_datetime(daily_bars["trade_date"]).max()
    selected = run_signal(
        stocks=stocks,
        daily_bars=daily_bars,
        hot_stocks=hot_stocks,
        stock_daily_basic=stock_daily_basic,
        trade_date=trade_date,
    )

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
