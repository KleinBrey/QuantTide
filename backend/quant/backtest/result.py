"""回测净值、收益、回撤和交易记录。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from math import sqrt
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

# 净值曲线和交易流水对外保持固定列顺序，空结果也返回相同结构。
EQUITY_COLUMNS = [
    "trade_date",
    "cash",
    "market_value",
    "total_equity",
    "net_value",
    "daily_return",
    "drawdown",
]

TRADE_COLUMNS = [
    "trade_date",
    "signal_date",
    "symbol",
    "name",
    "side",  # BUY 表示买入，SELL 表示卖出。
    "price",  # 实际成交价。
    "quantity",  # 成交股数。
    "gross_amount",
    "position_pct",  # 买入时占账户资金的比例。
    "stop_loss_price",  # 止损价。
    "take_profit_price",  # 止盈价。
    "fee",
    "cash_after",
    "realized_pnl",  # 卖出后实际实现的盈亏。
    "return_pct",  # 已平仓交易的收益率。
    "reason",  # 买卖原因,
]

# confirm_buy 为确认 K 线成立后收盘买入。
# stop_loss 为价格触及止损价后卖出。


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    """回测核心绩效指标。"""

    # 账户整体表现
    initial_cash: float
    final_equity: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    calmar_ratio: float

    # 交易数量和胜率
    trade_count: int
    opening_count: int
    closed_trade_count: int
    win_rate: float

    # 已平仓交易的收益质量
    average_trade_return: float
    average_winning_return: float
    average_losing_return: float
    payoff_ratio: float | None
    profit_factor: float | None
    expectancy_return: float
    average_holding_days: float


@dataclass(slots=True)
class BacktestResult:
    """完整回测结果。"""

    initial_cash: float
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    final_positions: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def metrics(self) -> PerformanceMetrics:
        """从净值曲线和交易记录计算绩效。"""

        # 没有净值数据时统一返回零值，调用方无需单独处理空回测。
        if self.equity_curve.empty:
            return PerformanceMetrics(
                initial_cash=self.initial_cash,
                final_equity=self.initial_cash,
                total_return=0.0,
                annualized_return=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                calmar_ratio=0.0,
                trade_count=0,
                opening_count=0,
                closed_trade_count=0,
                win_rate=0.0,
                average_trade_return=0.0,
                average_winning_return=0.0,
                average_losing_return=0.0,
                payoff_ratio=None,
                profit_factor=None,
                expectancy_return=0.0,
                average_holding_days=0.0,
            )

        # 账户总权益包含现金和持仓市值；相邻交易日的变化形成日收益率。
        equity = self.equity_curve["total_equity"].astype(float)
        daily_returns = equity.pct_change(fill_method=None).dropna()
        final_equity = float(equity.iloc[-1])
        total_return = final_equity / self.initial_cash - 1

        # 按 A 股一年约 252 个交易日，把区间累计收益折算成年化收益。
        periods = len(daily_returns)
        if periods and final_equity > 0:
            annualized_return = (final_equity / self.initial_cash) ** (
                252 / periods
            ) - 1
        else:
            annualized_return = 0.0

        # Sharpe 使用无风险利率为 0 的简化公式：日均收益 / 日波动 × √252。
        return_std = float(daily_returns.std(ddof=1)) if periods > 1 else 0.0
        sharpe_ratio = (
            sqrt(252) * float(daily_returns.mean()) / return_std
            if return_std > 0
            else 0.0
        )

        # 回撤表示当前权益相对历史最高权益的跌幅，最小值就是最大回撤。
        running_peak = equity.cummax()
        drawdown = equity / running_peak - 1
        max_drawdown = float(drawdown.min())
        # Calmar 衡量每承担一单位最大回撤获得的年化收益。
        calmar_ratio = (
            annualized_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
        )

        # BUY 是开仓记录，SELL 是已经完成盈亏结算的平仓记录。
        opening_trades = self.trades[self.trades["side"] == "BUY"]
        closed_trades = self.trades[self.trades["side"] == "SELL"]
        closed_count = len(closed_trades)
        # 胜率只统计已平仓交易，期末仍持有的仓位不参与。
        win_rate = (
            float((closed_trades["realized_pnl"] > 0).mean()) if closed_count else 0.0
        )
        # 分开统计盈利和亏损交易，便于观察平均赚多少、平均亏多少。
        returns = pd.to_numeric(closed_trades["return_pct"], errors="coerce").dropna()
        winning_returns = returns[returns > 0]
        losing_returns = returns[returns < 0]
        average_trade_return = float(returns.mean()) if not returns.empty else 0.0
        average_winning_return = (
            float(winning_returns.mean()) if not winning_returns.empty else 0.0
        )
        average_losing_return = (
            float(losing_returns.mean()) if not losing_returns.empty else 0.0
        )
        # 盈亏比 = 平均盈利收益率 / 平均亏损收益率绝对值。
        payoff_ratio = (
            average_winning_return / abs(average_losing_return)
            if average_losing_return < 0
            else None
        )

        # Profit Factor = 所有盈利金额之和 / 所有亏损金额绝对值之和。
        realized_pnl = pd.to_numeric(
            closed_trades["realized_pnl"], errors="coerce"
        ).dropna()
        gross_profit = float(realized_pnl[realized_pnl > 0].sum())
        gross_loss = abs(float(realized_pnl[realized_pnl < 0].sum()))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        # 单笔期望按盈利、亏损和持平交易的实际占比加权；数值上等于
        # 所有已平仓交易收益率的算术平均值。
        expectancy_return = average_trade_return
        average_holding_days = _average_holding_days(self.trades)

        return PerformanceMetrics(
            initial_cash=self.initial_cash,
            final_equity=final_equity,
            total_return=total_return,
            annualized_return=annualized_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            calmar_ratio=calmar_ratio,
            trade_count=len(self.trades),
            opening_count=len(opening_trades),
            closed_trade_count=closed_count,
            win_rate=win_rate,
            average_trade_return=average_trade_return,
            average_winning_return=average_winning_return,
            average_losing_return=average_losing_return,
            payoff_ratio=payoff_ratio,
            profit_factor=profit_factor,
            expectancy_return=expectancy_return,
            average_holding_days=average_holding_days,
        )

    def summary(self) -> dict[str, Any]:
        """返回适合终端或 API 序列化的摘要。"""

        metrics = self.metrics
        qualified_signal_count = self.metadata.get("qualified_signal_count", 0)
        return {
            "strategy": self.metadata.get("strategy"),
            "start_date": self.metadata.get("start_date"),
            "end_date": self.metadata.get("end_date"),
            "initial_cash": metrics.initial_cash,
            "final_equity": metrics.final_equity,
            "total_return": metrics.total_return,
            "annualized_return": metrics.annualized_return,
            "max_drawdown": metrics.max_drawdown,
            "sharpe_ratio": metrics.sharpe_ratio,
            "calmar_ratio": metrics.calmar_ratio,
            "trade_count": metrics.trade_count,
            "opening_count": metrics.opening_count,
            "closed_trade_count": metrics.closed_trade_count,
            "win_rate": metrics.win_rate,
            "average_trade_return": metrics.average_trade_return,
            "average_winning_return": metrics.average_winning_return,
            "average_losing_return": metrics.average_losing_return,
            "payoff_ratio": metrics.payoff_ratio,
            "profit_factor": metrics.profit_factor,
            "expectancy_return": metrics.expectancy_return,
            "average_holding_days": metrics.average_holding_days,
            "signal_days": self.metadata.get("signal_days", 0),
            "qualified_signal_count": qualified_signal_count,
            "executed_signal_count": self.metadata.get("executed_signal_count", 0),
            "skipped_full_position_count": self.metadata.get(
                "skipped_full_position_count", 0
            ),
            # 信号成交率 = 实际开仓次数 / 策略产生的合格信号数。
            "signal_execution_rate": (
                metrics.opening_count / qualified_signal_count
                if qualified_signal_count
                else 0.0
            ),
            "open_positions": len(self.final_positions),
        }


def _average_holding_days(trades: pd.DataFrame) -> float:
    """按买卖流水配对，计算已平仓交易的平均自然日持仓天数。"""

    # 回测不允许同一股票重复建仓，因此可以用 symbol 直接配对买卖记录。
    opened_at: dict[str, pd.Timestamp] = {}
    holding_days: list[int] = []
    for trade in trades.itertuples(index=False):
        symbol = str(trade.symbol)
        trade_date = pd.Timestamp(trade.trade_date).normalize()
        if trade.side == "BUY":
            opened_at[symbol] = trade_date
        elif trade.side == "SELL" and symbol in opened_at:
            # 使用日期差，因此统计的是自然日而不是交易日。
            holding_days.append((trade_date - opened_at.pop(symbol)).days)
    return (
        float(pd.Series(holding_days, dtype="float64").mean()) if holding_days else 0.0
    )


def build_equity_curve(
    rows: list[dict[str, Any]],
    *,
    initial_cash: float,
) -> pd.DataFrame:
    """组装净值曲线并补充日收益与回撤。"""

    curve = pd.DataFrame(rows)
    if curve.empty:
        return pd.DataFrame(columns=EQUITY_COLUMNS)

    # 净值以初始资金为 1；日收益率和回撤均由每日总权益推导。
    curve["net_value"] = curve["total_equity"] / initial_cash
    curve["daily_return"] = (
        curve["total_equity"].pct_change(fill_method=None).fillna(0.0)
    )
    curve["drawdown"] = curve["total_equity"] / curve["total_equity"].cummax() - 1
    return curve[EQUITY_COLUMNS]


def build_trade_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """组装字段稳定的交易记录。"""

    # 显式指定 columns，保证没有交易时前端仍能拿到完整表结构。
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """把 DataFrame 转成浏览器友好的 JSON 记录，并统一空值和日期。"""

    # 借助 pandas 的 JSON 转换统一处理 Timestamp、NaN 和 numpy 数值类型。
    records = json.loads(
        frame.to_json(
            orient="records",
            date_format="iso",
            date_unit="s",
            double_precision=15,
        )
    )
    # 页面只展示日期，去掉 ISO 字符串中的时分秒部分。
    date_fields = {
        column
        for column in frame.columns
        if column.endswith("_date") or column == "opened_at"
    }
    for record in records:
        for field_name in date_fields:
            value = record.get(field_name)
            if isinstance(value, str):
                record[field_name] = value[:10]
    return records


def format_backtest_result(
    result: BacktestResult,
    *,
    strategy: dict[str, object],
) -> dict[str, object]:
    """组装回测页面需要的摘要、交易流水和图表数据。"""

    # 这里是后端回测对象到前端 API 数据结构的唯一转换入口。
    return {
        "strategy": strategy,
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
            timespec="seconds"
        ),
        "summary": result.summary(),
        "trades": _frame_records(result.trades),
        "equity_curve": _frame_records(result.equity_curve),
        "final_positions": _frame_records(result.final_positions),
        "metadata": result.metadata,
    }
