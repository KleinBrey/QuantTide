"""放量突破次日确认策略的 A 股日频回测 MVP。

回测约定：

- 第一日出现放量上涨设置，第二日小阳线确认；
- 确认日按收盘价买入，单仓上限为当日账户权益的 1 / 最大持仓数；
- 持仓未满时按信号排名补仓，数量按 100 股整手向下取整；
- 止损价为设置日前一交易日收盘价，止盈价为买入价上方 2 倍风险距离；
- 遵守 A 股 T+1，买入当日不卖出；
- 日 K 同时触发止损和止盈时，保守地按止损先成交；
- 个股热度只用于排序，缺失时按放量强度排序。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from math import floor, isfinite
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
from backend.quant.backtest.account import Account
from backend.quant.backtest.position import Position
from backend.quant.backtest.result import (
    BacktestResult,
    build_equity_curve,
    build_trade_frame,
)
from backend.quant.strategy.implementations.today_confirmed_breakout import (
    TodayConfirmedBreakoutStrategy,
    RESULT_COLUMNS,
)

console = Console()


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """放量突破次日确认回测参数。"""

    initial_cash: float = 1_000_000.0
    start_date: str | date | None = None
    end_date: str | date | None = None
    lookback_months: int = 2
    max_positions: int = 10
    lot_size: int = 100
    commission_rate: float = 0.0
    minimum_commission: float = 0.0
    sell_tax_rate: float = 0.0

    def __post_init__(self) -> None:
        if not isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("initial_cash 必须大于 0")
        if self.lookback_months <= 0:
            raise ValueError("lookback_months 必须大于 0")
        if self.max_positions <= 0:
            raise ValueError("max_positions 必须大于 0")
        if self.lot_size <= 0:
            raise ValueError("lot_size 必须大于 0")
        if (
            min(
                self.commission_rate,
                self.minimum_commission,
                self.sell_tax_rate,
            )
            < 0
        ):
            raise ValueError("费率与最低佣金不能为负")


@dataclass(frozen=True, slots=True)
class BuyExecutionStats:
    """单个交易日的买入信号执行统计。"""

    executed: int = 0
    skipped_full: int = 0
    skipped_already_held: int = 0
    skipped_unexecutable: int = 0
    skipped_insufficient_cash: int = 0


class ConfirmedVolumeBreakoutBacktest:
    """只服务于放量突破次日确认策略的回测。"""

    strategy_id = "confirmed_volume_breakout"

    def __init__(
        self,
        config: BacktestConfig | None = None,
        strategy: TodayConfirmedBreakoutStrategy | None = None,
    ) -> None:
        self.config = config or BacktestConfig()
        self.strategy = strategy or TodayConfirmedBreakoutStrategy()

    def run(
        self,
        *,
        stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        hot_stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> BacktestResult:
        """执行回测并返回净值、交易记录和期末持仓。"""

        bars = self._prepare_bars(daily_bars)
        start_date, end_date = self._resolve_period(bars)
        calendar = self._trading_calendar(bars, start_date, end_date)
        signal_frames = []
        heat = hot_stocks.copy()
        if "trade_date" in heat.columns:
            heat["trade_date"] = pd.to_datetime(heat["trade_date"]).dt.normalize()

        for trade_date in calendar:
            breakout_date = bars.loc[
                bars["trade_date"] < trade_date, "trade_date"
            ].max()
            day_heat = heat
            if "trade_date" in heat.columns:
                day_heat = heat[heat["trade_date"] == breakout_date]

            selected = self.strategy.select(
                trade_date,
                stocks,
                bars,
                day_heat,
                stock_daily_basic,
            )
            if not selected.empty:
                signal_frames.append(selected)

        signals = (
            pd.concat(signal_frames, ignore_index=True)
            if signal_frames
            else pd.DataFrame(columns=RESULT_COLUMNS)
        )

        quotes = (
            bars.loc[
                bars["trade_date"].between(start_date, end_date),
                ["trade_date", "symbol", "open", "high", "low", "close"],
            ]
            .drop_duplicates(["trade_date", "symbol"], keep="last")
            .set_index(["trade_date", "symbol"])
            .sort_index()
        )
        signals_by_date = {
            confirm_date: group.sort_values(["selection_rank", "symbol"])
            for confirm_date, group in signals.groupby("confirm_date", sort=True)
        }

        account = Account(self.config.initial_cash)
        trade_rows: list[dict[str, Any]] = []
        equity_rows: list[dict[str, Any]] = []
        last_close_prices: dict[str, float] = {}
        executed_signal_count = 0
        skipped_full_position_count = 0
        skipped_already_held_count = 0
        skipped_unexecutable_count = 0
        skipped_insufficient_cash_count = 0

        for trade_date in calendar:
            day_quotes = quotes.loc[trade_date]
            if isinstance(day_quotes, pd.Series):
                day_quotes = day_quotes.to_frame().T
            day_quotes = day_quotes[~day_quotes.index.duplicated(keep="last")]

            self._execute_risk_exits(
                account=account,
                trade_date=trade_date.date(),
                day_quotes=day_quotes,
                trade_rows=trade_rows,
            )

            candidates = signals_by_date.get(trade_date)
            if candidates is not None and not candidates.empty:
                buy_stats = self._execute_close_buys(
                    account=account,
                    trade_date=trade_date.date(),
                    day_quotes=day_quotes,
                    candidates=candidates,
                    trade_rows=trade_rows,
                )
                executed_signal_count += buy_stats.executed
                skipped_full_position_count += buy_stats.skipped_full
                skipped_already_held_count += buy_stats.skipped_already_held
                skipped_unexecutable_count += buy_stats.skipped_unexecutable
                skipped_insufficient_cash_count += (
                    buy_stats.skipped_insufficient_cash
                )

            last_close_prices.update(day_quotes["close"].to_dict())
            market_value = account.market_value(last_close_prices)
            equity_rows.append(
                {
                    "trade_date": trade_date.date(),
                    "cash": account.cash,
                    "market_value": market_value,
                    "total_equity": account.cash + market_value,
                }
            )

        final_positions = pd.DataFrame(
            [
                {
                    "symbol": position.symbol,
                    "name": position.name,
                    "quantity": position.quantity,
                    "entry_price": position.entry_price,
                    "cost_price": position.cost_price,
                    "stop_loss_price": position.stop_loss_price,
                    "take_profit_price": position.take_profit_price,
                    "signal_date": position.signal_date,
                    "opened_at": position.opened_at,
                    "last_price": last_close_prices.get(
                        position.symbol, position.entry_price
                    ),
                    "market_value": position.market_value(
                        last_close_prices.get(position.symbol, position.entry_price)
                    ),
                }
                for position in account.positions.values()
            ]
        )

        hot_dates = pd.to_datetime(
            hot_stocks.get("trade_date", pd.Series(dtype="datetime64[ns]")),
            errors="coerce",
        ).dropna()
        metadata = {
            "strategy": self.strategy_id,
            "start_date": calendar[0].date().isoformat(),
            "end_date": calendar[-1].date().isoformat(),
            "max_positions": self.config.max_positions,
            "signal_days": int(signals["confirm_date"].nunique()),
            "qualified_signal_count": len(signals),
            "executed_signal_count": executed_signal_count,
            "skipped_full_position_count": skipped_full_position_count,
            "skipped_already_held_count": skipped_already_held_count,
            "skipped_unexecutable_count": skipped_unexecutable_count,
            "skipped_insufficient_cash_count": skipped_insufficient_cash_count,
            "hot_data_start": (
                hot_dates.min().date().isoformat() if not hot_dates.empty else None
            ),
            "hot_data_end": (
                hot_dates.max().date().isoformat() if not hot_dates.empty else None
            ),
            "assumptions": [
                "确认日使用完整日 K 产生信号，并假设能按收盘价成交",
                "单仓上限为当日账户权益的 1 / 最大持仓数",
                "持仓未满时按信号排名补仓，100 股整手，只做多",
                "买入当日不卖，从下一交易日起检查止损和止盈",
                "日内同时触发止损和止盈时按止损先成交",
                "历史热度缺失时仍产生信号，按放量强度排序",
                "市值过滤使用当前 stock_daily_basic 快照",
                "默认不计佣金、印花税、滑点、涨跌停和复权影响",
            ],
        }
        return BacktestResult(
            initial_cash=self.config.initial_cash,
            equity_curve=build_equity_curve(
                equity_rows,
                initial_cash=self.config.initial_cash,
            ),
            trades=build_trade_frame(trade_rows),
            final_positions=final_positions,
            metadata=metadata,
        )

    @staticmethod
    def _prepare_bars(daily_bars: pd.DataFrame) -> pd.DataFrame:
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
        dates = bars.loc[
            bars["trade_date"].between(start_date, end_date), "trade_date"
        ].drop_duplicates()
        calendar = pd.DatetimeIndex(dates.sort_values())
        if calendar.empty:
            raise ValueError("指定区间内没有交易日")
        return calendar

    def _execute_risk_exits(
        self,
        *,
        account: Account,
        trade_date: date,
        day_quotes: pd.DataFrame,
        trade_rows: list[dict[str, Any]],
    ) -> None:
        for symbol, position in list(account.positions.items()):
            if position.opened_at >= trade_date or symbol not in day_quotes.index:
                continue
            quote = day_quotes.loc[symbol]
            decision = self._exit_decision(position, quote)
            if decision is None:
                continue

            exit_price, reason = decision
            gross_amount = position.quantity * exit_price
            fee = self._transaction_fee(gross_amount, side="SELL")
            sold_position, realized_pnl = account.sell(
                symbol=symbol,
                price=exit_price,
                fee=fee,
            )
            trade_rows.append(
                {
                    "trade_date": trade_date,
                    "signal_date": sold_position.signal_date,
                    "symbol": symbol,
                    "name": sold_position.name,
                    "side": "SELL",
                    "price": exit_price,
                    "quantity": sold_position.quantity,
                    "gross_amount": gross_amount,
                    "position_pct": None,
                    "stop_loss_price": sold_position.stop_loss_price,
                    "take_profit_price": sold_position.take_profit_price,
                    "fee": fee,
                    "cash_after": account.cash,
                    "realized_pnl": realized_pnl,
                    "return_pct": realized_pnl / sold_position.cost_basis,
                    "reason": reason,
                }
            )

    @staticmethod
    def _exit_decision(
        position: Position,
        quote: pd.Series,
    ) -> tuple[float, str] | None:
        open_price = float(quote["open"])
        high_price = float(quote["high"])
        low_price = float(quote["low"])
        stop_price = position.stop_loss_price
        target_price = position.take_profit_price

        if open_price <= stop_price:
            return open_price, "stop_loss_gap"
        if open_price >= target_price:
            return open_price, "take_profit_gap"

        hit_stop = low_price <= stop_price
        hit_target = high_price >= target_price
        if hit_stop and hit_target:
            return stop_price, "stop_loss_same_day_ambiguous"
        if hit_stop:
            return stop_price, "stop_loss"
        if hit_target:
            return target_price, "take_profit"
        return None

    def _execute_close_buys(
        self,
        *,
        account: Account,
        trade_date: date,
        day_quotes: pd.DataFrame,
        candidates: pd.DataFrame,
        trade_rows: list[dict[str, Any]],
    ) -> BuyExecutionStats:
        executable: list[dict[str, Any]] = []
        skipped_already_held = 0
        skipped_unexecutable = 0
        seen_symbols = set(account.positions)
        for signal in candidates.to_dict(orient="records"):
            symbol = str(signal["symbol"])
            if symbol in seen_symbols:
                skipped_already_held += 1
                continue
            if symbol not in day_quotes.index:
                skipped_unexecutable += 1
                continue
            close_price = float(day_quotes.loc[symbol, "close"])
            stop_price = float(signal["stop_loss_price"])
            target_price = float(signal["take_profit_price"])
            if 0 < stop_price < close_price < target_price:
                signal["execution_price"] = close_price
                executable.append(signal)
                seen_symbols.add(symbol)
            else:
                skipped_unexecutable += 1

        if not executable:
            return BuyExecutionStats(
                skipped_already_held=skipped_already_held,
                skipped_unexecutable=skipped_unexecutable,
            )

        available_slots = max(
            0,
            self.config.max_positions - len(account.positions),
        )
        if available_slots == 0:
            return BuyExecutionStats(
                skipped_full=len(executable),
                skipped_already_held=skipped_already_held,
                skipped_unexecutable=skipped_unexecutable,
            )

        close_prices = day_quotes["close"].astype(float).to_dict()
        portfolio_equity = account.total_equity(close_prices)
        target_budget = portfolio_equity / self.config.max_positions
        executed = 0
        skipped_full = 0
        skipped_insufficient_cash = 0
        for signal in executable:
            if len(account.positions) >= self.config.max_positions:
                skipped_full += 1
                continue
            symbol = str(signal["symbol"])
            price = float(signal["execution_price"])
            budget = min(target_budget, account.cash)
            quantity = self._affordable_quantity(budget, price)
            while quantity > 0:
                gross_amount = quantity * price
                fee = self._transaction_fee(gross_amount, side="BUY")
                if gross_amount + fee <= account.cash + 1e-8:
                    break
                quantity -= self.config.lot_size
            if quantity <= 0:
                skipped_insufficient_cash += 1
                continue

            gross_amount = quantity * price
            fee = self._transaction_fee(gross_amount, side="BUY")
            position = account.buy(
                symbol=symbol,
                name=str(signal["name"]),
                quantity=quantity,
                price=price,
                fee=fee,
                stop_loss_price=float(signal["stop_loss_price"]),
                take_profit_price=float(signal["take_profit_price"]),
                signal_date=pd.Timestamp(signal["breakout_date"]).date(),
                trade_date=trade_date,
            )
            trade_rows.append(
                {
                    "trade_date": trade_date,
                    "signal_date": position.signal_date,
                    "symbol": symbol,
                    "name": position.name,
                    "side": "BUY",
                    "price": price,
                    "quantity": quantity,
                    "gross_amount": gross_amount,
                    "position_pct": gross_amount / portfolio_equity,
                    "stop_loss_price": position.stop_loss_price,
                    "take_profit_price": position.take_profit_price,
                    "fee": fee,
                    "cash_after": account.cash,
                    "realized_pnl": None,
                    "return_pct": None,
                    "reason": "confirm_buy",
                }
            )
            executed += 1

        return BuyExecutionStats(
            executed=executed,
            skipped_full=skipped_full,
            skipped_already_held=skipped_already_held,
            skipped_unexecutable=skipped_unexecutable,
            skipped_insufficient_cash=skipped_insufficient_cash,
        )

    def _affordable_quantity(self, budget: float, price: float) -> int:
        if budget <= 0 or price <= 0:
            return 0
        gross_budget = budget
        if self.config.commission_rate > 0:
            gross_budget = max(
                0.0,
                budget
                - max(
                    budget * self.config.commission_rate,
                    self.config.minimum_commission,
                ),
            )
        lots = floor(gross_budget / price / self.config.lot_size)
        return lots * self.config.lot_size

    def _transaction_fee(self, gross_amount: float, *, side: str) -> float:
        commission = 0.0
        if self.config.commission_rate > 0:
            commission = max(
                gross_amount * self.config.commission_rate,
                self.config.minimum_commission,
            )
        sell_tax = gross_amount * self.config.sell_tax_rate if side == "SELL" else 0.0
        return commission + sell_tax


def load_backtest_data(
    database: DuckDBDatabase | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """从本地 A 股数据库读取回测所需数据。"""

    database = database or DuckDBDatabase()
    return (
        StockRepository(database).get_table_data(),
        DailyBarRepository(database).get_table_data(),
        StockHotDailyRepository(database).get_table_data(),
        StockDailyBasicRepository(database).get_table_data(),
    )


def run_from_database(config: BacktestConfig | None = None) -> BacktestResult:
    """使用本地 DuckDB 执行放量突破次日确认回测。"""

    stocks, daily_bars, hot_stocks, stock_daily_basic = load_backtest_data()
    return ConfirmedVolumeBreakoutBacktest(config).run(
        stocks=stocks,
        daily_bars=daily_bars,
        hot_stocks=hot_stocks,
        stock_daily_basic=stock_daily_basic,
    )


def _render_result(result: BacktestResult) -> None:
    summary = result.summary()
    table = Table(title="放量突破次日确认回测 MVP")
    table.add_column("指标")
    table.add_column("结果", justify="right")
    table.add_row("回测区间", f"{summary['start_date']} ~ {summary['end_date']}")
    table.add_row("初始资金", f"{summary['initial_cash']:,.2f}")
    table.add_row("期末资产", f"{summary['final_equity']:,.2f}")
    table.add_row("累计收益率", f"{summary['total_return']:.2%}")
    table.add_row("年化收益率", f"{summary['annualized_return']:.2%}")
    table.add_row("最大回撤", f"{summary['max_drawdown']:.2%}")
    table.add_row("Sharpe", f"{summary['sharpe_ratio']:.3f}")
    table.add_row("有效信号日", str(summary["signal_days"]))
    table.add_row("合格信号数", str(summary["qualified_signal_count"]))
    table.add_row("成交数（买入）", str(summary["executed_signal_count"]))
    table.add_row(
        "因满仓跳过数",
        str(summary["skipped_full_position_count"]),
    )
    table.add_row("交易记录", str(summary["trade_count"]))
    table.add_row("已平仓股票", str(summary["closed_trade_count"]))
    table.add_row("胜率", f"{summary['win_rate']:.2%}")
    table.add_row("期末未平仓", str(summary["open_positions"]))
    console.print(table)

    if not result.trades.empty:
        console.print("\n[bold]交易记录[/bold]")
        columns = [
            "trade_date",
            "symbol",
            "name",
            "side",
            "price",
            "quantity",
            "position_pct",
            "stop_loss_price",
            "take_profit_price",
            "realized_pnl",
            "return_pct",
            "reason",
        ]
        console.print(result.trades[columns].to_string(index=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A 股放量突破次日确认回测 MVP")
    parser.add_argument("--start-date", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", help="结束日期 YYYY-MM-DD")
    parser.add_argument(
        "--months",
        type=int,
        default=2,
        help="未指定开始日期时回看月数（默认 2）",
    )
    parser.add_argument("--max-positions", type=int, default=10, help="等权持仓数")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = BacktestConfig(
        initial_cash=args.initial_cash,
        start_date=args.start_date,
        end_date=args.end_date,
        lookback_months=args.months,
        max_positions=args.max_positions,
    )
    with console.status("[bold green]正在读取本地数据并回测..."):
        result = run_from_database(config)
    _render_result(result)


if __name__ == "__main__":
    main()
