"""强势突破后缩量回调，再放量上涨企稳的选股策略。"""

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

# 让中文和特殊 Unicode 字符在终端表格中尽量正确对齐。
pd.set_option("display.unicode.east_asian_width", True)
pd.set_option("display.unicode.ambiguous_as_wide", True)

REQUIRED_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume"]

SIGNAL_COLUMNS = [
    "symbol",
    "date",
    "close",
    "return_1d",
    "return_5d",
    "volume_ratio",
    "breakout_return",
    "pullback_depth",
    "pullback_volume_ratio",
]

RESULT_COLUMNS = [
    "symbol",
    "name",
    "exchange",
    "market_cap",
    "latest_date",
    "latest_close",
    "latest_1d_pct",
    "latest_5d_pct",
    "volume_ratio",
    "breakout_return",
    "pullback_depth",
    "pullback_volume_ratio",
    "signal_stage",
    "hot_rank",
    "hot_value",
]


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """策略参数"""

    # 突破前高的观察天数。
    prior_high_days: int = 20
    # 突破阶段持续天数。
    breakout_days: int = 5
    # 突破阶段最小涨幅 10%。
    min_breakout_return: float = 0.10
    # 回调至少持续 3 天，最多持续 20 天。
    min_pullback_days: int = 3
    max_pullback_days: int = 20
    # 回调均量最多为突破均量的 80%。
    max_pullback_volume_ratio: float = 0.80
    # 回调最大跌幅 30%。
    max_pullback_depth: float = 0.30
    # 确认日实体涨幅至少 2%。
    min_confirm_body: float = 0.02
    # 确认日收盘价至少位于日内振幅的 65% 位置。
    min_confirm_close_position: float = 0.65
    # 确认日成交量至少为回调均量的 1.3 倍。
    min_confirm_volume_ratio: float = 1.30

    @property
    def required_days(self) -> int:
        """判断最新信号最多需要的交易日数量。"""

        return self.prior_high_days + self.breakout_days + self.max_pullback_days + 1


DEFAULT_CONFIG = StrategyConfig()


def load_market_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """读取本地股票、日 K 和最新热度数据。"""

    database = DuckDBDatabase()
    stocks = StockRepository(database).get_table_data()
    daily_bars = DailyBarRepository(database).get_table_data()
    hot_stocks = StockHotDailyRepository(database).get_latest()
    stock_daily_basic = StockDailyBasicRepository(database).get_table_data()
    return stocks, daily_bars, hot_stocks, stock_daily_basic


def find_latest_signal(
    bars: pd.DataFrame,
    config: StrategyConfig,
) -> dict[str, object] | None:
    """判断单只股票的最新交易日是否完成三阶段形态。"""

    latest_index = len(bars) - 1
    minimum_days = (
        config.prior_high_days
        + config.breakout_days
        + config.min_pullback_days
    )
    if latest_index < minimum_days:
        return None

    latest = bars.iloc[latest_index]
    previous = bars.iloc[latest_index - 1]
    candle_range = latest["high"] - latest["low"]
    close_position = (
        (latest["close"] - latest["low"]) / candle_range
        if candle_range > 0
        else 0
    )
    body_return = latest["close"] / latest["open"] - 1

    # 最新 K 线先满足“中阳线企稳”，再向前寻找对应的突破和回调段。
    if (
        latest["close"] <= previous["close"]
        or body_return < config.min_confirm_body
        or close_position < config.min_confirm_close_position
    ):
        return None

    first_breakout_end = max(
        config.prior_high_days + config.breakout_days - 1,
        latest_index - config.max_pullback_days - 1,
    )
    last_breakout_end = latest_index - config.min_pullback_days - 1

    for breakout_end in range(last_breakout_end, first_breakout_end - 1, -1):
        breakout_start = breakout_end - config.breakout_days + 1
        history = bars.iloc[
            breakout_start - config.prior_high_days : breakout_start
        ]
        breakout = bars.iloc[breakout_start : breakout_end + 1]
        pullback = bars.iloc[breakout_end + 1 : latest_index]

        breakout_return = breakout.iloc[-1]["close"] / history.iloc[-1]["close"] - 1
        if (
            breakout_return < config.min_breakout_return
            or breakout.iloc[-1]["close"] < breakout["close"].max()
            or breakout.iloc[-1]["close"] <= history["high"].max()
        ):
            continue

        breakout_volume = breakout["volume"].mean()
        pullback_volume = pullback["volume"].mean()
        pullback_volume_ratio = pullback_volume / breakout_volume
        pullback_depth = pullback["low"].min() / breakout["high"].max() - 1
        volume_ratio = latest["volume"] / pullback_volume

        if (
            pullback_volume_ratio > config.max_pullback_volume_ratio
            or pullback_depth < -config.max_pullback_depth
            or volume_ratio < config.min_confirm_volume_ratio
            or latest["close"] <= pullback["high"].tail(3).max()
        ):
            continue

        return {
            "symbol": latest["symbol"],
            "date": latest["date"],
            "close": latest["close"],
            "return_1d": latest["close"] / previous["close"] - 1,
            "return_5d": latest["close"] / bars.iloc[latest_index - 5]["close"] - 1,
            "volume_ratio": volume_ratio,
            "breakout_return": breakout_return,
            "pullback_depth": pullback_depth,
            "pullback_volume_ratio": pullback_volume_ratio,
        }

    return None


def run_strong_breakout_pullback_strategy(
    df: pd.DataFrame,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """按股票分组，返回最新交易日形成放量企稳信号的股票。"""

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in df]
    if missing_columns:
        raise ValueError(f"日 K 数据缺少字段：{', '.join(missing_columns)}")

    bars = df.copy()
    bars["date"] = pd.to_datetime(bars["date"], errors="raise")
    for column in ["open", "high", "low", "close", "volume"]:
        bars[column] = pd.to_numeric(bars[column], errors="raise")
    bars = bars[(bars["open"] > 0) & (bars["volume"] > 0)]

    # 排序、去重和截取窗口只做一次，逐只股票时直接判断信号。
    bars = (
        bars.sort_values(["symbol", "date"])
        .drop_duplicates(["symbol", "date"], keep="last")
        .groupby("symbol", sort=False)
        .tail(config.required_days)
        .reset_index(drop=True)
    )

    signals = []
    for _, symbol_bars in bars.groupby("symbol", sort=False):
        signal = find_latest_signal(symbol_bars.reset_index(drop=True), config)
        if signal:
            signals.append(signal)

    result = pd.DataFrame(signals, columns=SIGNAL_COLUMNS)
    if result.empty:
        return result
    return result[result["date"] == bars["date"].max()].reset_index(drop=True)


def run_strategy(
    *,
    stocks: pd.DataFrame,
    daily_bars: pd.DataFrame,
    hot_stocks: pd.DataFrame,
    stock_daily_basic: pd.DataFrame,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """计算最新交易日的突破回调企稳信号。"""

    if daily_bars.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    signals = run_strong_breakout_pullback_strategy(
        daily_bars.rename(columns={"trade_date": "date"}),
        config=config,
    ).rename(
        columns={
            "date": "latest_date",
            "close": "latest_close",
            "return_1d": "latest_1d_pct",
            "return_5d": "latest_5d_pct",
        }
    )
    if signals.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    signals["signal_stage"] = "放量企稳"
    stock_info = stocks.merge(
        stock_daily_basic,
        on="symbol",
        how="left",
    )

    hot_stocks = hot_stocks.drop_duplicates("symbol").reset_index(drop=True)
    hot_stocks["hot_rank"] = hot_stocks.index + 1

    return (
        stock_info.merge(signals, on="symbol")
        .merge(
            hot_stocks[["symbol", "hot_rank", "hot_value"]],
            on="symbol",
            how="left",
        )
        .sort_values(
            ["hot_rank", "latest_1d_pct"],
            ascending=[True, False],
            na_position="last",
        )[RESULT_COLUMNS]
        .reset_index(drop=True)
    )


if __name__ == "__main__":
    with console.status("[bold green]正在读取本地数据并计算突破回调策略..."):
        stocks, daily_bars, hot_stocks, stock_daily_basic = load_market_data()
        latest_date = pd.to_datetime(daily_bars["trade_date"]).max()
        latest_trade_date = (
            latest_date.strftime("%Y-%m-%d") if pd.notna(latest_date) else "无数据"
        )
        selected_stocks = run_strategy(
            stocks=stocks,
            daily_bars=daily_bars,
            hot_stocks=hot_stocks,
            stock_daily_basic=stock_daily_basic,
        )

    console.rule(f"今日:{date.today():%Y-%m-%d} 最新交易日:{latest_trade_date}")
    console.print("[green]✓ 策略计算完成[/green]")

    if selected_stocks.empty:
        console.print("[yellow]当前交易日没有突破回调企稳信号。[/yellow]")
    else:
        display = selected_stocks.copy()
        display["market_cap"] = (display["market_cap"] / 1e8).round(2)
        display["latest_close"] = display["latest_close"].round(2)
        display["latest_1d_pct"] = (display["latest_1d_pct"] * 100).round(2)
        display["latest_5d_pct"] = (display["latest_5d_pct"] * 100).round(2)
        display["volume_ratio"] = display["volume_ratio"].round(2)
        display["breakout_return"] = (display["breakout_return"] * 100).round(2)
        display["pullback_depth"] = (display["pullback_depth"] * 100).round(2)
        display["pullback_volume_ratio"] = display[
            "pullback_volume_ratio"
        ].round(2)

        console.print(
            display[
                [
                    "symbol",
                    "name",
                    "market_cap",
                    "latest_close",
                    "latest_1d_pct",
                    "latest_5d_pct",
                    "volume_ratio",
                    "breakout_return",
                    "pullback_depth",
                    "pullback_volume_ratio",
                    "signal_stage",
                    "hot_rank",
                ]
            ].rename(
                columns={
                    "symbol": "股票代码",
                    "name": "股票名称",
                    "market_cap": "市值(亿)",
                    "latest_close": "最新价",
                    "latest_1d_pct": "今日涨幅(%)",
                    "latest_5d_pct": "5日涨幅(%)",
                    "volume_ratio": "确认量比",
                    "breakout_return": "突破涨幅(%)",
                    "pullback_depth": "回调幅度(%)",
                    "pullback_volume_ratio": "回调量比",
                    "signal_stage": "信号阶段",
                    "hot_rank": "热度排名",
                }
            )
        )
        console.print(f"[green]共筛选出 {len(display)} 只股票。[/green]")
