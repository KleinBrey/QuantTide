"""二次反弹到前高后的做空信号策略。

策略只识别信号，不执行交易：

    前高 -> 明显回落 -> 第二次反弹到前高 -> 放量拒绝 K 线 -> 下跌跟随

所有判断只使用当前及历史日 K，不使用未来数据。
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
    StockHotDailyRepository,
    StockRepository,
)

console = Console()

# 让中文和特殊 Unicode 字符在终端表格中尽量正确对齐。
pd.set_option("display.unicode.east_asian_width", True)
pd.set_option("display.unicode.ambiguous_as_wide", True)

REQUIRED_COLUMNS = [
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
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
    "first_peak",
    "pullback_depth",
    "upper_wick_ratio",
    "bear_body_ratio",
    "signal_stage",
    "hot_rank",
    "hot_value",
]


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """策略参数"""

    peak_lookback_days: int = 60
    peak_min_gap_days: int = 10
    pullback_lookback_days: int = 30
    min_pullback: float = 0.08
    second_peak_min_ratio: float = 0.95
    second_peak_max_ratio: float = 1.03
    volume_average_days: int = 20
    min_volume_ratio: float = 1.5
    min_upper_wick_ratio: float = 0.30
    min_bear_body_ratio: float = 0.50
    min_bear_return: float = -0.025
    max_rejection_close_position: float = 0.55
    max_follow_close_position: float = 0.50
    min_follow_return: float = -0.02
    # 本地日 K 成交额单位为千元，20 万即 2 亿元。
    min_amount: float = 200_000


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


def _shift_by_symbol(
    df: pd.DataFrame,
    series: pd.Series,
    periods: int = 1,
) -> pd.Series:
    """在股票分组内位移。"""

    return series.groupby(df["symbol"], sort=False, dropna=False).shift(periods)


def _rolling_by_symbol(
    df: pd.DataFrame,
    series: pd.Series,
    window: int,
    operation: str,
) -> pd.Series:
    """在股票分组内执行 rolling，并恢复为原 DataFrame 的行索引。"""

    rolling = series.groupby(
        df["symbol"],
        sort=False,
        dropna=False,
    ).rolling(window)
    return getattr(rolling, operation)().reset_index(level=0, drop=True)


def calculate_indicators(
    df: pd.DataFrame,
    config: StrategyConfig,
) -> pd.DataFrame:
    """原地计算前高、二次反弹、拒绝 K 线和跟随信号。"""

    result = df
    previous_close = _shift_by_symbol(result, result["close"])

    result["return_1d"] = result["close"] / previous_close - 1
    result["return_5d"] = (
        result["close"] / _shift_by_symbol(result, result["close"], 5) - 1
    )

    # 前高必须至少出现在 10 个交易日以前，给中间回落和再次反弹留出空间。
    peak_window = config.peak_lookback_days - config.peak_min_gap_days
    previous_high = _shift_by_symbol(
        result,
        result["high"],
        config.peak_min_gap_days,
    )
    result["first_peak"] = _rolling_by_symbol(
        result,
        previous_high,
        peak_window,
        "max",
    )
    result["pullback_low"] = _rolling_by_symbol(
        result,
        _shift_by_symbol(result, result["low"]),
        config.pullback_lookback_days,
        "min",
    )
    result["pullback_depth"] = result["pullback_low"] / result["first_peak"] - 1

    second_peak_ratio = result["high"] / result["first_peak"]
    result["second_rally"] = (
        (result["pullback_depth"] <= -config.min_pullback)
        & second_peak_ratio.between(
            config.second_peak_min_ratio,
            config.second_peak_max_ratio,
        )
    )

    result["volume_ma20"] = _rolling_by_symbol(
        result,
        _shift_by_symbol(result, result["volume"]),
        config.volume_average_days,
        "mean",
    )
    result["volume_ratio"] = result["volume"] / result["volume_ma20"]

    candle_range = result["high"] - result["low"]
    candle_range = candle_range.where(candle_range != 0)
    result["close_position"] = (result["close"] - result["low"]) / candle_range
    result["upper_wick_ratio"] = (
        result["high"] - result[["open", "close"]].max(axis=1)
    ) / candle_range
    result["bear_body_ratio"] = (
        (result["open"] - result["close"]) / candle_range
    ).clip(lower=0)

    result["long_upper_wick"] = (
        (result["upper_wick_ratio"] >= config.min_upper_wick_ratio)
        & (result["close_position"] <= config.max_rejection_close_position)
    )
    result["big_bear"] = (
        (result["close"] < result["open"])
        & (result["bear_body_ratio"] >= config.min_bear_body_ratio)
        & (result["return_1d"] <= config.min_bear_return)
    )

    result["rejection_signal"] = (
        result["second_rally"]
        & (result["volume_ratio"] >= config.min_volume_ratio)
        & (result["long_upper_wick"] | result["big_bear"])
        & (result["amount"] >= config.min_amount)
    )

    previous_rejection = _shift_by_symbol(result, result["rejection_signal"])
    strong_follow = (
        result["close"] < _shift_by_symbol(result, result["low"])
    ) | (
        result["return_1d"] <= config.min_follow_return
    )
    result["follow_signal"] = (
        previous_rejection.astype(bool)
        & (result["close"] < result["open"])
        & (result["close"] < previous_close)
        & (result["close_position"] <= config.max_follow_close_position)
        & strong_follow
    )
    result["signal"] = result["follow_signal"]

    # 确认日显示前一天拒绝 K 线的指标，更容易判断信号来源。
    for column in [
        "first_peak",
        "pullback_depth",
        "volume_ratio",
        "upper_wick_ratio",
        "bear_body_ratio",
    ]:
        result[f"rejection_{column}"] = _shift_by_symbol(result, result[column])

    return result


def run_second_rebound_short_strategy(
    df: pd.DataFrame,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """按股票分组计算二次冲高做空信号。"""

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in df]
    if missing_columns:
        raise ValueError(f"日 K 数据缺少字段：{', '.join(missing_columns)}")

    bars = df.copy()
    bars["date"] = pd.to_datetime(bars["date"], errors="raise")
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        bars[column] = pd.to_numeric(bars[column], errors="raise")

    bars = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    return calculate_indicators(bars, config)


def latest_filter_counts(signals: pd.DataFrame) -> list[tuple[str, int]]:
    """统计最新交易日的高位做空筛选漏斗。"""

    latest = signals.groupby("symbol", sort=False).tail(1)
    return [
        ("已有10至60日前高", int(latest["first_peak"].notna().sum())),
        ("回落≥8%后第二次反弹到前高", int(latest["second_rally"].sum())),
        ("高位放量长上影或大阴线", int(latest["rejection_signal"].sum())),
        ("次日继续下跌确认", int(latest["follow_signal"].sum())),
    ]


def latest_confirmed_signals(signals: pd.DataFrame) -> pd.DataFrame:
    """提取最新确认信号，并使用拒绝日的形态指标。"""

    latest = signals.groupby("symbol", sort=False).tail(1).copy()
    latest = latest[latest["follow_signal"]].copy()
    for column in [
        "first_peak",
        "pullback_depth",
        "volume_ratio",
        "upper_wick_ratio",
        "bear_body_ratio",
    ]:
        latest[column] = latest[f"rejection_{column}"]
    return latest


def run_strategy(
    *,
    stocks: pd.DataFrame,
    daily_bars: pd.DataFrame,
    hot_stocks: pd.DataFrame,
    stock_daily_basic: pd.DataFrame,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """返回最新交易日得到下跌跟随确认的高位做空信号。"""

    if daily_bars.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    signals = run_second_rebound_short_strategy(
        daily_bars.rename(columns={"trade_date": "date"}),
        config=config,
    )
    latest = latest_confirmed_signals(signals).rename(
        columns={
            "date": "latest_date",
            "close": "latest_close",
            "return_1d": "latest_1d_pct",
            "return_5d": "latest_5d_pct",
        }
    )
    if latest.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    latest["signal_stage"] = "跟随确认"
    stock_info = stocks.merge(
        stock_daily_basic,
        on="symbol",
        how="left",
    )
    stock_info = stock_info[
        ~stock_info["name"].str.contains("ST", na=False)
        & stock_info["exchange"].ne("BJ")
    ]

    hot_stocks = hot_stocks.drop_duplicates("symbol").reset_index(drop=True)
    hot_stocks["hot_rank"] = hot_stocks.index + 1

    return (
        stock_info.merge(latest, on="symbol")
        .merge(
            hot_stocks[["symbol", "hot_rank", "hot_value"]],
            on="symbol",
            how="left",
        )
        .sort_values(["hot_rank", "latest_1d_pct"], na_position="last")[
            RESULT_COLUMNS
        ]
        .reset_index(drop=True)
    )


if __name__ == "__main__":
    with console.status("[bold green]正在读取本地数据并计算二次冲高做空策略..."):
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
        console.print("[yellow]当前交易日没有二次冲高做空确认信号。[/yellow]")
    else:
        display = selected_stocks.copy()
        display["market_cap"] = (display["market_cap"] / 1e8).round(2)
        display["latest_close"] = display["latest_close"].round(2)
        display["latest_1d_pct"] = (display["latest_1d_pct"] * 100).round(2)
        display["latest_5d_pct"] = (display["latest_5d_pct"] * 100).round(2)
        display["volume_ratio"] = display["volume_ratio"].round(2)
        display["first_peak"] = display["first_peak"].round(2)
        display["pullback_depth"] = (display["pullback_depth"] * 100).round(2)
        display["upper_wick_ratio"] = (
            display["upper_wick_ratio"] * 100
        ).round(2)
        display["bear_body_ratio"] = (display["bear_body_ratio"] * 100).round(2)

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
                    "first_peak",
                    "pullback_depth",
                    "upper_wick_ratio",
                    "bear_body_ratio",
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
                    "volume_ratio": "拒绝日量比",
                    "first_peak": "前高",
                    "pullback_depth": "中间回落(%)",
                    "upper_wick_ratio": "上影占比(%)",
                    "bear_body_ratio": "阴线实体(%)",
                    "signal_stage": "信号阶段",
                    "hot_rank": "热度排名",
                }
            )
        )
        console.print(f"[green]共筛选出 {len(display)} 只股票。[/green]")
