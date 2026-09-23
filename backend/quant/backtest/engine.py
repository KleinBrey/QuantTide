"""放量突破次日确认策略的 A 股日频回测执行器。

资金与成交约定：

- 只做多，最多同时持有 ``max_positions`` 只股票，同一股票不重复买入；
- 每只新仓的资金预算不超过买入前账户总权益的 ``max_position_pct``；
- 实际买入预算取目标资金预算与可用现金的较小值，不融资、不重新平衡旧仓；
- 按当日信号排名依次买入，持仓达到上限后忽略剩余信号；
- 买入数量按 ``lot_size`` 向下取整，并为佣金预留现金；不足一手则跳过；
- 信号仅在确认日按收盘价尝试成交，未成交信号不会顺延到下一交易日；
- 遵守 A 股 T+1，买入当日不卖出；满足任一卖出条件时整仓卖出；
- 所有卖出条件均在收盘后判断并按收盘价成交，不使用日内最高价或最低价；
- 止盈止损均未触发时，较前收跌幅大于 5% 则按收盘价卖出；
- 连续 3 根阴线且每根实体跌幅大于 2% 时，按第三根阴线收盘价卖出；
- 每日收盘后按最新可用收盘价计算持仓市值与账户权益。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import floor
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
)

console = Console()


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """回测时间、账户和卖出条件。"""

    # 时间范围
    # 回测开始日期；未指定时按 lookback_months 从结束日期向前推算。
    start_date: str | date | None = None
    # 回测结束日期；未指定时使用行情中的最新交易日。
    end_date: str | date | None = None
    # 未指定开始日期时向前回看的自然月数。
    lookback_months: int = 6

    # 交易账户
    # 回测初始资金，单位为元。
    initial_cash: float = 1_000_000.0
    # 账户允许同时持有的最大股票数量。
    max_positions: int = 20
    # 单只股票的建仓金额最多占买入前账户总权益的 5%。
    max_position_pct: float = 0.05
    # 每手股票的股数，买入数量按此整数倍向下取整。
    lot_size: int = 100
    # 买卖佣金费率，使用小数表示，例如 0.0003 代表万分之三。
    commission_rate: float = 0.0005
    # 每笔交易的最低佣金，单位为元。
    minimum_commission: float = 5
    # 卖出时收取的税率，使用小数表示；买入时不收取。
    sell_tax_rate: float = 0.006

    # 卖出条件
    # 当日收盘价较前一交易日收盘价跌幅严格大于 5% 时卖出。
    previous_close_decline_exit_pct: float = 0.05
    # 连续 3 根阴线且每根实体跌幅严格大于 2% 时卖出。
    consecutive_bearish_candle_count: int = 3
    consecutive_bearish_body_pct: float = 0.02


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

        # 1. 准备回测区间、交易日历、行情和策略信号。
        bars = self._prepare_bars(daily_bars)
        start_date, end_date = self._resolve_period(bars)
        calendar = self._trading_calendar(bars, start_date, end_date)
        heat = hot_stocks.copy()
        if "trade_date" in heat.columns:
            heat["trade_date"] = pd.to_datetime(heat["trade_date"]).dt.normalize()

        signals = self.strategy.select_range(
            calendar,
            stocks,
            bars,
            heat,
            stock_daily_basic,
        )

        quotes = self._prepare_quotes(bars, start_date, end_date)
        signals_by_date = {
            confirm_date: group.sort_values(["selection_rank", "symbol"])
            for confirm_date, group in signals.groupby("confirm_date", sort=True)
        }

        # 2. 初始化账户、每日状态和回测统计。
        account = Account(self.config.initial_cash)
        trade_rows: list[dict[str, Any]] = []
        equity_rows: list[dict[str, Any]] = []
        last_close_prices: dict[str, float] = {}
        bearish_candle_streaks: dict[str, int] = {}
        executed_signal_count = 0
        skipped_full_position_count = 0
        skipped_already_held_count = 0
        skipped_unexecutable_count = 0
        skipped_insufficient_cash_count = 0

        # 3. 按交易日依次执行卖出、买入和收盘估值。
        for trade_date in calendar:
            day_quotes = quotes.loc[trade_date]
            if isinstance(day_quotes, pd.Series):
                day_quotes = day_quotes.to_frame().T
            day_quotes = day_quotes[~day_quotes.index.duplicated(keep="last")]

            self._execute_risk_exits(
                account=account,
                trade_date=trade_date.date(),
                day_quotes=day_quotes,
                previous_close_prices=last_close_prices,
                bearish_candle_streaks=bearish_candle_streaks,
                trade_rows=trade_rows,
            )

            # 先卖后买，释放的现金和仓位可以用于当天的新信号。
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
                skipped_insufficient_cash_count += buy_stats.skipped_insufficient_cash

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

        # 4. 组装期末持仓和结果摘要。
        final_positions = self._build_final_positions(account, last_close_prices)

        hot_dates = pd.to_datetime(
            hot_stocks.get("trade_date", pd.Series(dtype="datetime64[ns]")),
            errors="coerce",
        ).dropna()
        metadata = {
            "strategy": self.strategy_id,
            "start_date": calendar[0].date().isoformat(),
            "end_date": calendar[-1].date().isoformat(),
            "max_positions": self.config.max_positions,
            "max_position_pct": self.config.max_position_pct,
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
                f"单只股票建仓上限为当日账户权益的 {self.config.max_position_pct:.0%}",
                f"持仓未满时按信号排名补仓，{self.config.lot_size} 股整手，只做多",
                "买入当日不卖，从下一交易日起检查止损和止盈",
                "所有卖出条件均按收盘价判断并按收盘价成交",
                (
                    "较前一交易日收盘跌幅大于 "
                    f"{self.config.previous_close_decline_exit_pct:.0%} 时卖出"
                ),
                (
                    f"连续 {self.config.consecutive_bearish_candle_count} 根阴线且"
                    "每根实体跌幅大于 "
                    f"{self.config.consecutive_bearish_body_pct:.0%} 时卖出"
                ),
                "历史热度缺失时仍产生信号，按放量强度排序",
                "市值过滤使用确认日当日或此前最近可用的历史市值",
                "佣金和卖出税率按配置计算，不计滑点、涨跌停和复权影响",
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
    def _build_final_positions(
        account: Account,
        last_close_prices: dict[str, float],
    ) -> pd.DataFrame:
        """按最后可用收盘价整理期末持仓。"""

        rows: list[dict[str, Any]] = []
        for position in account.positions.values():
            last_price = last_close_prices.get(position.symbol, position.entry_price)
            rows.append(
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
                    "last_price": last_price,
                    "market_value": position.market_value(last_price),
                }
            )
        return pd.DataFrame(rows)

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

    @staticmethod
    def _prepare_quotes(
        bars: pd.DataFrame,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
    ) -> pd.DataFrame:
        """生成按日期和股票索引的回测成交行情。"""

        return (
            bars.loc[
                bars["trade_date"].between(start_date, end_date),
                ["trade_date", "symbol", "open", "close"],
            ]
            .set_index(["trade_date", "symbol"])
            .sort_index()
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

    def _execute_risk_exits(
        self,
        *,
        account: Account,
        trade_date: date,
        day_quotes: pd.DataFrame,
        trade_rows: list[dict[str, Any]],
        previous_close_prices: dict[str, float] | None = None,
        bearish_candle_streaks: dict[str, int] | None = None,
    ) -> None:
        """检查已有持仓的卖出条件，并记录实际成交。"""

        previous_close_prices = previous_close_prices or {}
        if bearish_candle_streaks is None:
            bearish_candle_streaks = {}

        for symbol, position in list(account.positions.items()):
            # A 股 T+1：买入当天不允许卖出；停牌无行情时也无法成交。
            if position.opened_at >= trade_date or symbol not in day_quotes.index:
                continue

            quote = day_quotes.loc[symbol]
            bearish_candle_streaks[symbol] = self._next_bearish_streak(
                quote,
                bearish_candle_streaks.get(symbol, 0),
            )

            decision = self._exit_decision(
                position,
                quote,
                previous_close=previous_close_prices.get(symbol),
                consecutive_bearish_count=bearish_candle_streaks[symbol],
            )
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
            bearish_candle_streaks.pop(symbol, None)
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

    def _exit_decision(
        self,
        position: Position,
        quote: pd.Series,
        previous_close: float | None = None,
        consecutive_bearish_count: int = 0,
    ) -> tuple[float, str] | None:
        """按优先级返回收盘卖出价格和原因；无需卖出时返回 None。"""

        close_price = float(quote["close"])
        stop_price = position.stop_loss_price
        target_price = position.take_profit_price

        # 止损和止盈优先于其他收盘风控条件。
        if close_price <= stop_price:
            return close_price, "stop_loss"
        if close_price >= target_price:
            return close_price, "take_profit"

        if previous_close is not None and previous_close > 0:
            previous_close_decline_pct = (previous_close - close_price) / previous_close
            if previous_close_decline_pct > self.config.previous_close_decline_exit_pct:
                return close_price, "previous_close_decline"

        if consecutive_bearish_count >= self.config.consecutive_bearish_candle_count:
            return close_price, "consecutive_bearish_candles"

        return None

    def _next_bearish_streak(
        self,
        quote: pd.Series,
        current_streak: int,
    ) -> int:
        """更新连续大阴线计数；当前 K 线不满足条件时归零。"""

        open_price = float(quote["open"])
        close_price = float(quote["close"])
        body_decline_pct = (open_price - close_price) / open_price
        if (
            close_price < open_price
            and body_decline_pct > self.config.consecutive_bearish_body_pct
        ):
            return current_streak + 1
        return 0

    def _execute_close_buys(
        self,
        *,
        account: Account,
        trade_date: date,
        day_quotes: pd.DataFrame,
        candidates: pd.DataFrame,
        trade_rows: list[dict[str, Any]],
    ) -> BuyExecutionStats:
        """按信号顺序在收盘价买入，并返回执行统计。"""

        # 先剔除已持仓、缺少行情或价格关系无效的信号。
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

        if len(account.positions) >= self.config.max_positions:
            return BuyExecutionStats(
                skipped_full=len(executable),
                skipped_already_held=skipped_already_held,
                skipped_unexecutable=skipped_unexecutable,
            )

        close_prices = day_quotes["close"].astype(float).to_dict()
        portfolio_equity = account.total_equity(close_prices)
        # 单股预算独立于最大持仓数，始终按账户总权益的固定比例计算。
        target_budget = portfolio_equity * self.config.max_position_pct
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
        """在预算内计算可买的整手股数，并预留买入佣金。"""

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
        """计算单笔交易的佣金和卖出税费。"""

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
    """在终端输出回测核心指标。"""

    summary = result.summary()
    table = Table(title="放量突破次日确认回测")
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


def main() -> None:
    """从本地数据库运行默认回测。"""

    config = BacktestConfig()
    with console.status("[bold green]正在读取本地数据并回测..."):
        result = run_from_database(config)
    _render_result(result)


if __name__ == "__main__":
    main()
