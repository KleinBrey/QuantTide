"""回测净值、收益、回撤和交易记录。"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Any

import pandas as pd

# 让中文和特殊 Unicode 字符在终端表格中尽量正确对齐。
pd.set_option("display.unicode.east_asian_width", True)
pd.set_option("display.unicode.ambiguous_as_wide", True)

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

    initial_cash: float
    final_equity: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    trade_count: int
    closed_trade_count: int
    win_rate: float


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

        if self.equity_curve.empty:
            return PerformanceMetrics(
                initial_cash=self.initial_cash,
                final_equity=self.initial_cash,
                total_return=0.0,
                annualized_return=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                trade_count=0,
                closed_trade_count=0,
                win_rate=0.0,
            )

        equity = self.equity_curve["total_equity"].astype(float)
        daily_returns = equity.pct_change(fill_method=None).dropna()
        final_equity = float(equity.iloc[-1])
        total_return = final_equity / self.initial_cash - 1

        periods = len(daily_returns)
        if periods and final_equity > 0:
            annualized_return = (final_equity / self.initial_cash) ** (
                252 / periods
            ) - 1
        else:
            annualized_return = 0.0

        return_std = float(daily_returns.std(ddof=1)) if periods > 1 else 0.0
        sharpe_ratio = (
            sqrt(252) * float(daily_returns.mean()) / return_std
            if return_std > 0
            else 0.0
        )

        running_peak = equity.cummax()
        drawdown = equity / running_peak - 1
        max_drawdown = float(drawdown.min())

        closed_trades = self.trades[self.trades["side"] == "SELL"]
        closed_count = len(closed_trades)
        win_rate = (
            float((closed_trades["realized_pnl"] > 0).mean()) if closed_count else 0.0
        )

        return PerformanceMetrics(
            initial_cash=self.initial_cash,
            final_equity=final_equity,
            total_return=total_return,
            annualized_return=annualized_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            trade_count=len(self.trades),
            closed_trade_count=closed_count,
            win_rate=win_rate,
        )

    def summary(self) -> dict[str, Any]:
        """返回适合终端或 API 序列化的摘要。"""

        metrics = self.metrics
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
            "trade_count": metrics.trade_count,
            "closed_trade_count": metrics.closed_trade_count,
            "win_rate": metrics.win_rate,
            "signal_days": self.metadata.get("signal_days", 0),
            "open_positions": len(self.final_positions),
        }


def build_equity_curve(
    rows: list[dict[str, Any]],
    *,
    initial_cash: float,
) -> pd.DataFrame:
    """组装净值曲线并补充日收益与回撤。"""

    curve = pd.DataFrame(rows)
    if curve.empty:
        return pd.DataFrame(columns=EQUITY_COLUMNS)

    curve["net_value"] = curve["total_equity"] / initial_cash
    curve["daily_return"] = (
        curve["total_equity"].pct_change(fill_method=None).fillna(0.0)
    )
    curve["drawdown"] = curve["total_equity"] / curve["total_equity"].cummax() - 1
    return curve[EQUITY_COLUMNS]


def build_trade_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """组装字段稳定的交易记录。"""

    return pd.DataFrame(rows, columns=TRADE_COLUMNS)
