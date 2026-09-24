"""放量突破次日确认策略的 A 股日频回测执行器。

资金与成交约定：

- 只做多，最多同时持有 ``max_positions`` 只股票，同一股票不重复买入；
- 每只新仓的资金预算不超过买入前账户总权益的 ``max_position_pct``；
- 实际买入预算取目标资金预算与可用现金的较小值，不融资、不重新平衡旧仓；
- 按当日信号排名依次买入，持仓达到上限后忽略剩余信号；
- 买入数量按 ``lot_size`` 向下取整，并为佣金预留现金；不足一手则跳过；
- 信号仅在确认日按收盘价尝试成交，未成交信号不会顺延到下一交易日；
- 遵守 A 股 T+1，买入当日不卖出；满足任一卖出条件时整仓卖出；
- 所有卖出条件均在收盘后判断并按收盘价成交；
- 卖出优先级：止损 > 止盈 > 策略卖出条件（大跌、连续下跌，见策略的 find_exits）；
- 每日收盘后按最新可用收盘价计算持仓市值与账户权益。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from math import floor, isinf
from typing import Any

import pandas as pd
from rich import box
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
from backend.quant.strategy.today_confirmed_breakout import (
    TodayConfirmedBreakoutStrategy,
)

console = Console()


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """回测时间和账户参数。卖出条件在策略的 StrategyConfig 里。"""

    # 时间范围
    # 回测开始日期；未指定时按 lookback_months 从结束日期向前推算。
    start_date: str | date | None = None
    # 回测结束日期；未指定时使用行情中的最新交易日。
    end_date: str | date | None = None
    # 未指定开始日期时向前回看的自然月数。
    lookback_months: int = 6

    # 交易账户
    # 回测初始资金，单位为元。
    initial_cash: float = 1_000_000_000_000.0
    # 账户允许同时持有的最大股票数量。
    max_positions: int = 100
    # 单只股票的建仓金额最多占买入前账户总权益的 1%。
    max_position_pct: float = 0.01
    # 每手股票的股数，买入数量按此整数倍向下取整。
    lot_size: int = 100
    # 买卖佣金费率，使用小数表示，例如 0.0003 代表万分之三。
    commission_rate: float = 0.0005
    # 每笔交易的最低佣金，单位为元。
    minimum_commission: float = 5
    # 卖出时收取的税率，使用小数表示；买入时不收取。
    sell_tax_rate: float = 0.006


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

        # 1. 确定回测区间和交易日历。
        bars = daily_bars
        start_date, end_date = self.resolve_period(bars)
        calendar = self.trading_calendar(bars, start_date, end_date)
        period_bars = bars[bars["trade_date"].between(start_date, end_date)]

        # 2. 由交易策略把形态信号转换为入场候选，并生成策略退出日。
        signals = self.strategy.generate_entries_range(
            calendar, stocks, bars, hot_stocks, stock_daily_basic
        )
        strategy_exits = self._find_strategy_exits(signals, period_bars)
        signals_by_date = {
            confirm_date: group.sort_values(["selection_rank", "symbol"])
            for confirm_date, group in signals.groupby("confirm_date", sort=True)
        }
        close_prices = (
            period_bars.drop_duplicates(["trade_date", "symbol"], keep="last")
            .set_index(["trade_date", "symbol"])["close"]
            .astype(float)
            .sort_index()
        )

        # 3. 按交易日依次执行卖出、买入和收盘估值。
        account = Account(self.config.initial_cash)
        trade_rows: list[dict[str, Any]] = []
        equity_rows: list[dict[str, Any]] = []
        last_close_prices: dict[str, float] = {}
        stats: Counter[str] = Counter()

        for trade_date in calendar:
            day_prices = close_prices.loc[trade_date].to_dict()
            last_close_prices.update(day_prices)
            today = trade_date.date()

            # 先卖后买，释放的现金和仓位可以用于当天的新信号。
            self._sell(account, today, day_prices, strategy_exits, trade_rows)

            candidates = signals_by_date.get(trade_date)
            if candidates is not None:
                self._buy(
                    account,
                    today,
                    day_prices,
                    last_close_prices,
                    candidates,
                    trade_rows,
                    stats,
                )

            market_value = account.market_value(last_close_prices)
            equity_rows.append(
                {
                    "trade_date": today,
                    "cash": account.cash,
                    "market_value": market_value,
                    "total_equity": account.cash + market_value,
                }
            )

        # 4. 组装期末持仓和结果摘要。
        hot_dates = pd.to_datetime(
            hot_stocks.get("trade_date", pd.Series(dtype="datetime64[ns]")),
            errors="coerce",
        ).dropna()
        strategy_config = self.strategy.config
        metadata = {
            "strategy": self.strategy_id,
            "start_date": calendar[0].date().isoformat(),
            "end_date": calendar[-1].date().isoformat(),
            "max_positions": self.config.max_positions,
            "max_position_pct": self.config.max_position_pct,
            "signal_days": int(signals["confirm_date"].nunique()),
            "qualified_signal_count": len(signals),
            "executed_signal_count": stats["executed"],
            "skipped_full_position_count": stats["skipped_full"],
            "skipped_already_held_count": stats["skipped_already_held"],
            "skipped_unexecutable_count": stats["skipped_unexecutable"],
            "skipped_insufficient_cash_count": stats["skipped_insufficient_cash"],
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
                "买入当日不卖，从下一交易日起检查卖出条件",
                "所有卖出条件均按收盘价判断并按收盘价成交，止损、止盈优先",
                (
                    "较前一交易日收盘跌幅大于 "
                    f"{strategy_config.previous_close_decline_exit_pct:.0%} 时卖出"
                ),
                (
                    f"连续 {strategy_config.consecutive_decline_day_count} 个交易日"
                    "的当日跌幅均大于 "
                    f"{strategy_config.consecutive_decline_pct:.0%} 时卖出"
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
            final_positions=self._build_final_positions(account, last_close_prices),
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # 区间与日历
    # ------------------------------------------------------------------
    def resolve_period(self, bars: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
        """根据配置和行情可用范围确定实际回测区间。"""

        available_start = bars["trade_date"].min()
        available_end = bars["trade_date"].max()

        if self.config.end_date is not None:
            end_date = pd.to_datetime(self.config.end_date, errors="raise").normalize()
        else:
            end_date = available_end
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
    def trading_calendar(
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

    # ------------------------------------------------------------------
    # 卖出
    # ------------------------------------------------------------------
    def _find_strategy_exits(
        self,
        signals: pd.DataFrame,
        period_bars: pd.DataFrame,
    ) -> dict[tuple[str, date], tuple[date, str]]:
        """让策略为每个信号找出入场后的第一个卖出日。

        返回 {(股票, 入场日): (卖出日, 卖出原因)}。入场日就是确认日，
        买入后 position.opened_at 与之相同，卖出时直接查表即可。
        """

        entries = signals[["symbol", "confirm_date"]].rename(
            columns={"confirm_date": "entry_date"}
        )
        exits = self.strategy.find_exits(entries, period_bars)
        return {
            (row.symbol, row.entry_date.date()): (row.exit_date.date(), row.exit_reason)
            for row in exits.itertuples()
        }

    def _sell(
        self,
        account: Account,
        trade_date: date,
        day_prices: dict[str, float],
        strategy_exits: dict[tuple[str, date], tuple[date, str]],
        trade_rows: list[dict[str, Any]],
    ) -> None:
        """检查持仓是否需要卖出，按收盘价整仓卖出并记录成交。"""

        for symbol, position in list(account.positions.items()):
            # A 股 T+1：买入当天不允许卖出；停牌无行情时也无法成交。
            if position.opened_at >= trade_date or symbol not in day_prices:
                continue

            price = day_prices[symbol]
            reason = self._exit_reason(position, price, trade_date, strategy_exits)
            if reason is None:
                continue

            gross_amount = position.quantity * price
            fee = self._transaction_fee(gross_amount, side="SELL")
            sold, realized_pnl = account.sell(symbol=symbol, price=price, fee=fee)
            trade_rows.append(
                {
                    "trade_date": trade_date,
                    "signal_date": sold.signal_date,
                    "symbol": symbol,
                    "name": sold.name,
                    "side": "SELL",
                    "price": price,
                    "quantity": sold.quantity,
                    "gross_amount": gross_amount,
                    "position_pct": None,
                    "stop_loss_price": sold.stop_loss_price,
                    "take_profit_price": sold.take_profit_price,
                    "fee": fee,
                    "cash_after": account.cash,
                    "realized_pnl": realized_pnl,
                    "return_pct": realized_pnl / sold.cost_basis,
                    "reason": reason,
                }
            )

    def _exit_reason(
        self,
        position: Position,
        price: float,
        trade_date: date,
        strategy_exits: dict[tuple[str, date], tuple[date, str]],
    ) -> str | None:
        """按优先级返回卖出原因：止损 > 止盈 > 策略卖出条件；无需卖出返回 None。"""

        risk_reason = self.strategy.risk_exit_reason(
            close_price=price,
            stop_loss_price=position.stop_loss_price,
            take_profit_price=position.take_profit_price,
        )
        if risk_reason is not None:
            return risk_reason

        exit_date, reason = strategy_exits.get(
            (position.symbol, position.opened_at), (None, None)
        )
        return reason if exit_date == trade_date else None

    # ------------------------------------------------------------------
    # 买入
    # ------------------------------------------------------------------
    def _buy(
        self,
        account: Account,
        trade_date: date,
        day_prices: dict[str, float],
        last_close_prices: dict[str, float],
        candidates: pd.DataFrame,
        trade_rows: list[dict[str, Any]],
        stats: Counter[str],
    ) -> None:
        """按信号排名依次在收盘价买入，并累计执行统计。"""

        equity = account.total_equity(last_close_prices)
        # 单股预算始终按买入前账户总权益的固定比例计算。
        target_budget = equity * self.config.max_position_pct

        for signal in candidates.to_dict(orient="records"):
            symbol = str(signal["symbol"])
            price = day_prices.get(symbol)
            stop_price = float(signal["stop_loss_price"])
            target_price = float(signal["take_profit_price"])

            if symbol in account.positions:
                stats["skipped_already_held"] += 1
                continue
            # 当日没有行情，或价格关系不满足 止损 < 收盘 < 止盈。
            if price is None or not 0 < stop_price < price < target_price:
                stats["skipped_unexecutable"] += 1
                continue
            if len(account.positions) >= self.config.max_positions:
                stats["skipped_full"] += 1
                continue

            quantity = self._affordable_quantity(
                min(target_budget, account.cash), price
            )
            if quantity <= 0:
                stats["skipped_insufficient_cash"] += 1
                continue

            gross_amount = quantity * price
            fee = self._transaction_fee(gross_amount, side="BUY")
            position = account.buy(
                symbol=symbol,
                name=str(signal["name"]),
                quantity=quantity,
                price=price,
                fee=fee,
                stop_loss_price=stop_price,
                take_profit_price=target_price,
                signal_date=pd.Timestamp(signal["breakout_date"]).date(),
                trade_date=trade_date,
            )
            stats["executed"] += 1
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
                    "position_pct": gross_amount / equity,
                    "stop_loss_price": position.stop_loss_price,
                    "take_profit_price": position.take_profit_price,
                    "fee": fee,
                    "cash_after": account.cash,
                    "realized_pnl": None,
                    "return_pct": None,
                    "reason": "confirm_buy",
                }
            )

    def _affordable_quantity(self, budget: float, price: float) -> int:
        """在预算内计算可买的整手股数，并为买入佣金预留资金。"""

        commission = max(
            budget * self.config.commission_rate, self.config.minimum_commission
        )
        lots = floor((budget - commission) / price / self.config.lot_size)
        return max(lots, 0) * self.config.lot_size

    def _transaction_fee(self, gross_amount: float, *, side: str) -> float:
        """计算单笔交易的佣金和卖出税费。"""

        commission = max(
            gross_amount * self.config.commission_rate, self.config.minimum_commission
        )
        sell_tax = gross_amount * self.config.sell_tax_rate if side == "SELL" else 0.0
        return commission + sell_tax

    # ------------------------------------------------------------------
    # 结果
    # ------------------------------------------------------------------
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
    """按策略表现、交易表现和执行统计输出回测指标。"""

    summary = result.summary()

    table = _metric_table()
    table.add_row("回测区间", f"{summary['start_date']} ~ {summary['end_date']}")
    table.add_row("初始资金", f"{int(summary['initial_cash']):,}")
    table.add_row("期末资产", f"{int(summary['final_equity']):,}")
    table.add_section()
    table.add_row("累计收益率", f"{summary['total_return']:.2%}")
    # table.add_row("年化收益率", f"{summary['annualized_return']:.2%}")
    # table.add_row("Sharpe", f"{summary['sharpe_ratio']:.3f}")
    # table.add_row("Calmar", f"{summary['calmar_ratio']:.3f}")

    table.add_row("合格信号数", str(summary["qualified_signal_count"]))
    table.add_row("开仓次数", str(summary["opening_count"]))
    table.add_row("最大回撤", f"{summary['max_drawdown']:.2%}")
    table.add_row("已平仓交易", str(summary["closed_trade_count"]))
    table.add_row("期末未平仓", str(summary["open_positions"]))
    table.add_section()
    table.add_row("胜率", f"{summary['win_rate']:.2%}")
    table.add_row("平均单笔收益率", f"{summary['average_trade_return']:+.2%}")
    table.add_row("平均盈利收益率", f"{summary['average_winning_return']:+.2%}")
    table.add_row("平均亏损收益率", f"{summary['average_losing_return']:+.2%}")
    table.add_row("盈亏比", _format_ratio(summary["payoff_ratio"]))
    # table.add_row("Profit Factor", _format_ratio(summary["profit_factor"]))
    # table.add_row("单笔期望收益率", f"{summary['expectancy_return']:+.2%}")
    table.add_row("平均持仓天数", f"{summary['average_holding_days']:.1f}")
    table.add_section()

    table.add_row("信号成交率", f"{summary['signal_execution_rate']:.2%}")
    table.add_row("满仓跳过", str(summary["skipped_full_position_count"]))
    console.print(table)


def _metric_table() -> Table:
    """创建与终端示例一致的双列表格。"""

    table = Table(
        title="回测统计",
        title_justify="center",
        box=box.SQUARE,
        show_edge=True,
        pad_edge=False,
        width=50,
    )
    table.add_column("指标")
    table.add_column("结果", justify="right")
    return table


def _format_ratio(value: float | None) -> str:
    """以两位小数显示比率，并友好表示无穷或无可用数据。"""

    if value is None:
        return "—"
    return "∞" if isinf(value) and value > 0 else f"{value:.2f}"


def main() -> None:
    """从本地数据库运行默认回测。"""

    config = BacktestConfig()
    with console.status("[bold green]正在读取本地数据并回测..."):
        result = run_from_database(config)
    _render_result(result)


if __name__ == "__main__":
    main()
