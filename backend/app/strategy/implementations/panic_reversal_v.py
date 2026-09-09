"""恐慌下跌 V 字反弹策略。

持续下跌 -> 下跌加速/恐慌放量 -> 反转 K 线 -> 次日确认

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

REQUIRED_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume"]

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
    "drawdown_20",
    "signal_stage",
    "panic_signal",
    "reversal_signal",
    "confirmed_signal",
    "hot_rank",
    "hot_value",
]


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """策略参数"""

    # 恐慌阶段：最近 6 个交易日内统计收跌天数。
    panic_down_window: int = 6
    # 恐慌阶段：最近窗口内至少 4 天收跌。
    panic_min_down_days: int = 4
    # 恐慌阶段：当前收盘价相对近 20 日最高价至少回撤 10%。
    panic_drawdown: float = -0.10
    # 恐慌阶段：最近 5 日跌幅至少达到 14 日 ATR 波动率的 2.5 倍。
    panic_atr_multiple: float = 2.5
    # 恐慌阶段：当日成交量至少为此前 20 日均量的 1.5 倍。
    panic_volume_ratio: float = 1.5

    # 反转阶段：长下影或大阳线成交量至少为此前 20 日均量的 1.3 倍。
    reversal_volume_ratio: float = 1.3
    # 反转阶段：下影线至少占当日振幅的 35%。
    long_wick_ratio: float = 0.35
    # 反转阶段：长下影 K 线收盘价至少位于日内振幅的 65% 位置。
    reversal_close_position: float = 0.65
    # 反转阶段：大阳线或高开走强收盘价至少位于日内振幅的 70% 位置。
    big_bull_close_position: float = 0.70
    # 恐慌信号出现后的 3 个交易日内，反转 K 线仍可触发反转信号。
    panic_valid_days: int = 3


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
    """在股票分组内位移；单股辅助函数也可继续独立使用。"""

    if "symbol" not in df.columns:
        return series.shift(periods)
    return series.groupby(df["symbol"], sort=False, dropna=False).shift(periods)


def _rolling_by_symbol(
    df: pd.DataFrame,
    series: pd.Series,
    window: int,
    operation: str,
) -> pd.Series:
    """在股票分组内执行 rolling，并恢复为原 DataFrame 的行索引。"""

    if "symbol" not in df.columns:
        return getattr(series.rolling(window), operation)()

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
    """原地计算收益率、ATR、量比和 K 线形态等基础指标。"""

    result = df
    previous_close = _shift_by_symbol(result, result["close"])

    result["return_1d"] = result["close"] / previous_close - 1
    result["return_5d"] = (
        result["close"] / _shift_by_symbol(result, result["close"], 5) - 1
    )
    # 在最近 6 根 K 线中统计收跌天数，用“下跌密度”过滤单日偶发暴跌。
    result["down_count"] = _rolling_by_symbol(
        result,
        result["return_1d"].lt(0),
        config.panic_down_window,
        "sum",
    )

    result["high_20"] = _rolling_by_symbol(result, result["high"], 20, "max")
    result["drawdown_20"] = result["close"] / result["high_20"] - 1

    true_range_1 = result["high"] - result["low"]
    true_range_2 = (result["high"] - previous_close).abs()
    true_range_3 = (result["low"] - previous_close).abs()
    # TR 同时覆盖日内振幅、向上跳空和向下跳空，ATR 才不会低估真实波动。
    result["tr"] = pd.concat([true_range_1, true_range_2, true_range_3], axis=1).max(
        axis=1
    )
    result["atr_14"] = _rolling_by_symbol(result, result["tr"], 14, "mean")
    result["atr_pct"] = result["atr_14"] / previous_close

    # 均量不包含今天，避免用今天的数据稀释今天的放量程度。
    previous_volume = _shift_by_symbol(result, result["volume"])
    result["volume_ma20"] = _rolling_by_symbol(
        result,
        previous_volume,
        20,
        "mean",
    )
    result["volume_ratio"] = result["volume"] / result["volume_ma20"]

    result["body"] = (result["close"] - result["open"]).abs()
    result["body_pct"] = result["body"] / previous_close
    result["is_bear"] = result["close"] < result["open"]
    result["is_bull"] = result["close"] > result["open"]

    result["body_ma3"] = _rolling_by_symbol(
        result,
        _shift_by_symbol(result, result["body_pct"]),
        3,
        "mean",
    )
    # 比较基准不含当天，避免大阴线自己抬高均值后反而无法被识别。
    result["large_bear"] = result["is_bear"] & (
        result["body_pct"] >= result["body_ma3"] * 1.3
    )

    # 一字线没有可比较的日内区间，影线比例和收盘位置保持为缺失值。
    candle_range = result["high"] - result["low"]
    result["range"] = candle_range.where(candle_range != 0)
    result["lower_wick"] = result[["open", "close"]].min(axis=1) - result["low"]
    result["lower_wick_ratio"] = result["lower_wick"] / result["range"]
    result["close_position"] = (result["close"] - result["low"]) / result["range"]

    return result


def calculate_panic_signal(
    df: pd.DataFrame,
    config: StrategyConfig,
) -> pd.DataFrame:
    """原地判断行情是否进入持续下跌后的恐慌区。"""

    result = df
    continuous_drop = result["down_count"] >= config.panic_min_down_days
    # 既接受相对 20 日高点的深度回撤，也接受按个股 ATR 标准化后的快速下跌。
    large_drop = (result["drawdown_20"] <= config.panic_drawdown) | (
        result["return_5d"] <= -result["atr_pct"] * config.panic_atr_multiple
    )
    panic_action = (
        result["volume_ratio"] >= config.panic_volume_ratio
    ) | result["large_bear"]

    # 三个阶段必须同时成立：持续下跌、跌幅足够、并出现放量或大阴线宣泄。
    result["panic_signal"] = continuous_drop & large_drop & panic_action
    return result


def calculate_reversal_signal(
    df: pd.DataFrame,
    config: StrategyConfig,
) -> pd.DataFrame:
    """原地识别恐慌发生后 3 个交易日内出现的反转 K 线。"""

    result = df
    previous_close = _shift_by_symbol(result, result["close"])

    # 长下影且收在日内高位，表示盘中抛压被承接；放量用于确认承接有效。
    result["long_lower_wick"] = (
        (result["lower_wick_ratio"] >= config.long_wick_ratio)
        & (result["close_position"] >= config.reversal_close_position)
        & (result["volume_ratio"] >= config.reversal_volume_ratio)
    )

    bull_body_pct = (result["close"] - result["open"]) / previous_close
    # 大阳线实体以昨日收盘价归一化，并用 ATR 判断是否显著超过日常波动。
    result["big_bull"] = (
        result["is_bull"]
        & (bull_body_pct >= result["atr_pct"] * 1.2)
        & (result["close_position"] >= config.big_bull_close_position)
        & (result["volume_ratio"] >= config.reversal_volume_ratio)
    )

    # 收盘站上昨日最高价，比盘中短暂突破更能体现买方持续占优。
    previous_high = _shift_by_symbol(result, result["high"])
    result["strong_reclaim"] = result["is_bull"] & (
        result["close"] > previous_high
    )
    gap_up = result["open"] > previous_close * 1.01
    # 高开后继续收强，排除高开低走造成的假突破。
    result["gap_and_run"] = (
        gap_up
        & result["is_bull"]
        & (result["close_position"] >= config.big_bull_close_position)
    )

    result["reversal_bar"] = (
        result["long_lower_wick"]
        | result["big_bull"]
        | result["strong_reclaim"]
        | result["gap_and_run"]
    )

    # shift(1) 确保今天的 panic_signal 不会用于今天自己的反转判断。
    previous_panic = _shift_by_symbol(result, result["panic_signal"])
    result["recent_panic"] = (
        _rolling_by_symbol(
            result,
            previous_panic,
            config.panic_valid_days,
            "max",
        )
        .fillna(0)
        .astype(bool)
    )
    result["reversal_signal"] = result["recent_panic"] & result["reversal_bar"]
    return result


def calculate_confirmed_signal(df: pd.DataFrame) -> pd.DataFrame:
    """原地确认反转信号后的下一交易日是否继续走强。"""

    result = df
    previous_reversal = (
        _shift_by_symbol(result, result["reversal_signal"])
        .fillna(False)
        .astype(bool)
    )
    previous_high = _shift_by_symbol(result, result["high"])
    previous_close = _shift_by_symbol(result, result["close"])
    breaks_previous_high = result["close"] > previous_high
    bullish_follow_through = result["is_bull"] & (
        result["close"] >= previous_close
    )

    # 只在反转后的第一根 K 线上确认：突破昨日高点，或阳线收盘不低于昨日。
    result["confirmed_signal"] = previous_reversal & (
        breaks_previous_high | bullish_follow_through
    )
    return result


def run_panic_reversal_strategy(
    df: pd.DataFrame,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """运行完整策略；多只股票会按 ``symbol`` 分组独立计算。"""

    missing_columns = [
        column for column in REQUIRED_COLUMNS if column not in df.columns
    ]
    if missing_columns:
        missing_text = ", ".join(missing_columns)
        raise ValueError(f"日 K 数据缺少字段：{missing_text}")

    if df.empty:
        return df.copy()

    bars = df.copy()
    bars["date"] = pd.to_datetime(bars["date"], errors="raise")
    for column in ["open", "high", "low", "close", "volume"]:
        bars[column] = pd.to_numeric(bars[column], errors="raise")

    # 整体排序后，每个阶段都以全市场分组向量化方式在同一个 DataFrame 上
    # 追加指标，避免复制百万行数据。
    bars = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    bars = calculate_indicators(bars, config)
    bars = calculate_panic_signal(bars, config)
    bars = calculate_reversal_signal(bars, config)
    bars = calculate_confirmed_signal(bars)
    return bars


def show_signals(df: pd.DataFrame) -> None:
    """打印 Panic、Reversal 或 Confirmed 信号及其主要触发原因。"""

    columns = [
        "symbol",
        "date",
        "close",
        "return_5d",
        "drawdown_20",
        "down_count",
        "volume_ratio",
        "panic_signal",
        "long_lower_wick",
        "big_bull",
        "strong_reclaim",
        "gap_and_run",
        "reversal_signal",
        "confirmed_signal",
    ]
    has_signal = df["panic_signal"] | df["reversal_signal"] | df["confirmed_signal"]
    print(df.loc[has_signal, columns].to_string(index=False))


def run_strategy(
    *,
    stocks: pd.DataFrame,
    daily_bars: pd.DataFrame,
    hot_stocks: pd.DataFrame,
    stock_daily_basic: pd.DataFrame,
    config: StrategyConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """计算最新交易日的恐慌、反转或确认信号。"""

    if daily_bars.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    signals = run_panic_reversal_strategy(
        daily_bars.rename(columns={"trade_date": "date"}),
        config=config,
    )
    latest = signals.groupby("symbol", sort=False).tail(1)
    latest = latest[
        latest["panic_signal"] | latest["reversal_signal"] | latest["confirmed_signal"]
    ].rename(
        columns={
            "date": "latest_date",
            "close": "latest_close",
            "return_1d": "latest_1d_pct",
            "return_5d": "latest_5d_pct",
        }
    )
    if latest.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    latest["signal_stage"] = "恐慌"
    latest.loc[latest["reversal_signal"], "signal_stage"] = "反转"
    latest.loc[latest["confirmed_signal"], "signal_stage"] = "确认"

    stock_info = stocks.merge(
        stock_daily_basic,
        on="symbol",
        how="left",
    )

    hot_stocks = hot_stocks.drop_duplicates("symbol").reset_index(drop=True)
    hot_stocks["hot_rank"] = hot_stocks.index + 1

    return (
        stock_info.merge(latest, on="symbol")
        .merge(hot_stocks[["symbol", "hot_rank", "hot_value"]], on="symbol")
        .sort_values("hot_rank")[RESULT_COLUMNS]
        .reset_index(drop=True)
    )


if __name__ == "__main__":
    with console.status("[bold green]正在读取本地数据并计算恐慌反转策略..."):
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
        console.print("[yellow]当前交易日没有恐慌、反转或确认信号。[/yellow]")
    else:
        display = selected_stocks.copy()
        display["market_cap"] = (display["market_cap"] / 1e8).round(2)
        display["latest_close"] = display["latest_close"].round(2)
        display["latest_1d_pct"] = (display["latest_1d_pct"] * 100).round(2)
        display["latest_5d_pct"] = (display["latest_5d_pct"] * 100).round(2)
        display["volume_ratio"] = display["volume_ratio"].round(2)
        display["drawdown_20"] = (display["drawdown_20"] * 100).round(2)

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
                    "drawdown_20",
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
                    "volume_ratio": "量比",
                    "drawdown_20": "20日回撤(%)",
                    "signal_stage": "信号阶段",
                    "hot_rank": "热度排名",
                }
            )
        )
        console.print(f"[green]共筛选出 {len(display)} 只股票。[/green]")
