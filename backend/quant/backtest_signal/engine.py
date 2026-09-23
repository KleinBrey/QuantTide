"""放量突破次日确认策略的无资金约束信号回测。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
from rich.console import Console
from rich.table import Table

from backend.app.database import DuckDBDatabase
from backend.app.repository import (
    DailyBarRepository,
    StockDailyBasicRepository,
    StockHotDailyRepository,
    StockRepository,
)
from backend.quant.strategy.implementations.today_confirmed_breakout import (
    TodayConfirmedBreakoutStrategy,
)

from backend.quant.backtest_signal.result import (
    SignalBacktestResult,
    build_signal_trade_frame,
)

console = Console()


@dataclass(frozen=True, slots=True)
class SignalBacktestConfig:
    """信号回测的时间范围和退出条件。"""

    start_date: str | date | None = None
    end_date: str | date | None = None
    lookback_months: int = 6
    previous_close_decline_exit_pct: float = 0.05
    consecutive_bearish_candle_count: int = 3
    consecutive_bearish_body_pct: float = 0.02

    def __post_init__(self) -> None:
        if self.lookback_months <= 0:
            raise ValueError("lookback_months 必须大于 0")
        if self.previous_close_decline_exit_pct < 0:
            raise ValueError("previous_close_decline_exit_pct 不能为负数")
        if self.consecutive_bearish_candle_count <= 0:
            raise ValueError("consecutive_bearish_candle_count 必须大于 0")
        if self.consecutive_bearish_body_pct < 0:
            raise ValueError("consecutive_bearish_body_pct 不能为负数")


class ConfirmedVolumeBreakoutSignalBacktest:
    """逐个独立评估信号，不维护账户、现金或持仓。"""

    strategy_id = "confirmed_volume_breakout_signal"

    def __init__(
        self,
        config: SignalBacktestConfig | None = None,
        strategy: TodayConfirmedBreakoutStrategy | None = None,
    ) -> None:
        self.config = config or SignalBacktestConfig()
        self.strategy = strategy or TodayConfirmedBreakoutStrategy()

    def run(
        self,
        *,
        stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        hot_stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> SignalBacktestResult:
        """生成历史信号并独立计算每个信号的退出和收益。"""

        bars = self._prepare_bars(daily_bars)
        start_date, end_date = self._resolve_period(bars)
        calendar = self._trading_calendar(bars, start_date, end_date)

        heat = hot_stocks.copy()
        if "trade_date" in heat.columns:
            heat["trade_date"] = pd.to_datetime(
                heat["trade_date"], errors="coerce"
            ).dt.normalize()

        signals = self.strategy.select_range(
            calendar,
            stocks,
            bars,
            heat,
            stock_daily_basic,
        )
        trades = self._evaluate_signals(
            signals=signals,
            bars=bars,
            end_date=end_date,
        )
        metadata = {
            "strategy": self.strategy_id,
            "start_date": calendar[0].date().isoformat(),
            "end_date": calendar[-1].date().isoformat(),
            "signal_days": int(signals["confirm_date"].nunique()),
            "qualified_signal_count": len(signals),
            "assumptions": [
                "每个合格信号独立评估，不维护账户、资金或持仓",
                "同一股票的重叠信号分别计算，互不影响",
                "确认日按收盘价进入，从下一交易日起检查退出条件",
                "退出规则与资金回测一致，均按收盘价判断和退出",
                "不计算佣金、税费、滑点和资金容量",
                "未触发退出的信号按回测截止日前最后收盘价计算收益",
            ],
        }
        return SignalBacktestResult(trades=trades, metadata=metadata)

    def _evaluate_signals(
        self,
        *,
        signals: pd.DataFrame,
        bars: pd.DataFrame,
        end_date: pd.Timestamp,
    ) -> pd.DataFrame:
        """按信号逐一计算退出结果。"""

        if signals.empty:
            return build_signal_trade_frame([])

        signal_symbols = signals["symbol"].astype("string").dropna().unique()
        signal_bars = bars[
            bars["symbol"].isin(signal_symbols) & (bars["trade_date"] <= end_date)
        ]
        bars_by_symbol = {
            str(symbol): symbol_bars.sort_values("trade_date").reset_index(drop=True)
            for symbol, symbol_bars in signal_bars.groupby("symbol", sort=False)
        }

        rows: list[dict[str, Any]] = []
        for sequence, signal in enumerate(
            signals.to_dict(orient="records"),
            start=1,
        ):
            row = self._evaluate_signal(
                sequence=sequence,
                signal=signal,
                bars_by_symbol=bars_by_symbol,
                end_date=end_date,
            )
            if row is not None:
                rows.append(row)

        return build_signal_trade_frame(rows)

    def _evaluate_signal(
        self,
        *,
        sequence: int,
        signal: dict[str, Any],
        bars_by_symbol: dict[str, pd.DataFrame],
        end_date: pd.Timestamp,
    ) -> dict[str, Any] | None:
        """计算单个信号从确认日至退出日的表现。"""

        symbol = str(signal["symbol"])
        symbol_bars = bars_by_symbol.get(symbol)
        if symbol_bars is None or symbol_bars.empty:
            return None

        entry_date = pd.Timestamp(signal["confirm_date"]).normalize()
        entry_quotes = symbol_bars[symbol_bars["trade_date"] == entry_date]
        if entry_quotes.empty:
            return None

        entry_price = float(entry_quotes.iloc[-1]["close"])
        stop_price = float(signal["stop_loss_price"])
        target_price = float(signal["take_profit_price"])
        if not 0 < stop_price < entry_price < target_price:
            return None

        previous_close = entry_price
        bearish_streak = 0
        holding_days = 0
        last_date = entry_date
        last_price = entry_price
        exit_date: date | None = None
        exit_price: float | None = None
        exit_reason = "end_of_period"

        future_bars = symbol_bars[
            (symbol_bars["trade_date"] > entry_date)
            & (symbol_bars["trade_date"] <= end_date)
        ]
        for _, quote in future_bars.iterrows():
            holding_days += 1
            last_date = pd.Timestamp(quote["trade_date"])
            last_price = float(quote["close"])
            bearish_streak = self._next_bearish_streak(quote, bearish_streak)
            decision = self._exit_decision(
                close_price=last_price,
                stop_price=stop_price,
                target_price=target_price,
                previous_close=previous_close,
                consecutive_bearish_count=bearish_streak,
            )
            if decision is not None:
                exit_price, exit_reason = decision
                exit_date = last_date.date()
                last_price = exit_price
                break
            previous_close = last_price

        status = "closed" if exit_date is not None else "open"
        return {
            "signal_id": f"{symbol}:{entry_date:%Y%m%d}:{sequence}",
            "symbol": symbol,
            "name": str(signal["name"]),
            "signal_date": pd.Timestamp(signal["breakout_date"]).date(),
            "entry_date": entry_date.date(),
            "entry_price": entry_price,
            "exit_date": exit_date,
            "exit_price": exit_price,
            "last_date": last_date.date(),
            "last_price": last_price,
            "stop_loss_price": stop_price,
            "take_profit_price": target_price,
            "holding_days": holding_days,
            "return_pct": last_price / entry_price - 1,
            "status": status,
            "reason": exit_reason,
        }

    def _exit_decision(
        self,
        *,
        close_price: float,
        stop_price: float,
        target_price: float,
        previous_close: float | None,
        consecutive_bearish_count: int,
    ) -> tuple[float, str] | None:
        """按优先级返回信号退出价格和原因。"""

        if close_price <= stop_price:
            return close_price, "stop_loss"
        if close_price >= target_price:
            return close_price, "take_profit"
        if previous_close is not None and previous_close > 0:
            decline_pct = (previous_close - close_price) / previous_close
            if decline_pct > self.config.previous_close_decline_exit_pct:
                return close_price, "previous_close_decline"
        if consecutive_bearish_count >= self.config.consecutive_bearish_candle_count:
            return close_price, "consecutive_bearish_candles"
        return None

    def _next_bearish_streak(
        self,
        quote: pd.Series,
        current_streak: int,
    ) -> int:
        """更新连续大阴线计数。"""

        open_price = float(quote["open"])
        close_price = float(quote["close"])
        body_decline_pct = (open_price - close_price) / open_price
        if (
            close_price < open_price
            and body_decline_pct > self.config.consecutive_bearish_body_pct
        ):
            return current_streak + 1
        return 0

    @staticmethod
    def _prepare_bars(daily_bars: pd.DataFrame) -> pd.DataFrame:
        """清洗日 K，并保证每只股票每天只有一条有效行情。"""

        required = {
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
        }
        missing = sorted(required.difference(daily_bars.columns))
        if missing:
            raise ValueError(f"日 K 数据缺少字段：{', '.join(missing)}")

        bars = daily_bars.copy()
        bars["symbol"] = bars["symbol"].astype("string")
        bars["trade_date"] = pd.to_datetime(
            bars["trade_date"], errors="coerce"
        ).dt.normalize()
        for column in ["open", "high", "low", "close", "volume"]:
            bars[column] = pd.to_numeric(bars[column], errors="coerce")
        bars = bars.dropna(subset=list(required))
        bars = bars[
            (bars["open"] > 0)
            & (bars["high"] > 0)
            & (bars["low"] > 0)
            & (bars["close"] > 0)
            & (bars["volume"] > 0)
        ]
        return (
            bars.drop_duplicates(["symbol", "trade_date"], keep="last")
            .sort_values(["symbol", "trade_date"])
            .reset_index(drop=True)
        )

    def _resolve_period(self, bars: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
        """根据配置和行情可用范围确定实际回测区间。"""

        if bars.empty:
            raise ValueError("日 K 数据为空，无法回测")

        available_start = bars["trade_date"].min()
        available_end = bars["trade_date"].max()
        end_date = (
            pd.to_datetime(self.config.end_date, errors="raise").normalize()
            if self.config.end_date is not None
            else available_end
        )
        end_date = min(end_date, available_end)
        if self.config.start_date is not None:
            start_date = pd.to_datetime(
                self.config.start_date, errors="raise"
            ).normalize()
        else:
            start_date = end_date - pd.DateOffset(months=self.config.lookback_months)
        start_date = max(start_date, available_start)
        if start_date > end_date:
            raise ValueError("回测开始日期不能晚于结束日期")
        return start_date, end_date

    @staticmethod
    def _trading_calendar(
        bars: pd.DataFrame,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
    ) -> pd.DatetimeIndex:
        """提取回测区间内的交易日。"""

        dates = bars.loc[
            bars["trade_date"].between(start_date, end_date), "trade_date"
        ].drop_duplicates()
        calendar = pd.DatetimeIndex(dates.sort_values())
        if calendar.empty:
            raise ValueError("指定区间内没有交易日")
        return calendar


def load_backtest_data(
    database: DuckDBDatabase | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """从本地 A 股数据库读取信号回测所需数据。"""

    database = database or DuckDBDatabase()
    return (
        StockRepository(database).get_table_data(),
        DailyBarRepository(database).get_table_data(),
        StockHotDailyRepository(database).get_table_data(),
        StockDailyBasicRepository(database).get_table_data(),
    )


def run_from_database(
    config: SignalBacktestConfig | None = None,
) -> SignalBacktestResult:
    """使用本地 DuckDB 执行独立信号回测。"""

    stocks, daily_bars, hot_stocks, stock_daily_basic = load_backtest_data()
    return ConfirmedVolumeBreakoutSignalBacktest(config).run(
        stocks=stocks,
        daily_bars=daily_bars,
        hot_stocks=hot_stocks,
        stock_daily_basic=stock_daily_basic,
    )


def _render_result(result: SignalBacktestResult) -> None:
    """在终端输出信号回测摘要。"""

    summary = result.summary()
    table = Table(title="放量突破信号回测（无资金约束）")
    table.add_column("指标")
    table.add_column("结果", justify="right")
    table.add_row("测试区间", f"{summary['start_date']} ~ {summary['end_date']}")
    table.add_row("", "")
    table.add_row("总信号数", str(summary["qualified_signal_count"]))
    table.add_row("可评估信号数", str(summary["executable_signal_count"]))
    table.add_row("已退出信号数", str(summary["closed_signal_count"]))
    table.add_row("未退出信号数", str(summary["open_signal_count"]))
    table.add_row("", "")
    table.add_row("盈利信号数", str(summary["positive_signal_count"]))
    table.add_row("信号胜率", f"{summary['positive_signal_rate']:.2%}")
    table.add_row("已退出胜率", f"{summary['win_rate']:.2%}")
    table.add_row("", "")
    table.add_row("平均单笔收益率", f"{summary['average_return']:.2%}")
    table.add_row("收益率中位数", f"{summary['median_return']:.2%}")
    table.add_row("最大单笔收益", f"{summary['best_return']:.2%}")
    table.add_row("最大单笔亏损", f"{summary['worst_return']:.2%}")
    table.add_row("平均持有期", f"{summary['average_holding_days']:.2f} 日")
    console.print(table)


def main() -> None:
    """从本地数据库运行默认信号回测。"""

    with console.status("[bold green]正在读取本地数据并进行信号回测..."):
        result = run_from_database()
    _render_result(result)


if __name__ == "__main__":
    main()
