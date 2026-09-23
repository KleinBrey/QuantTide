"""不考虑资金和仓位约束的独立信号回测结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

SIGNAL_TRADE_COLUMNS = [
    "signal_id",
    "symbol",
    "name",
    "signal_date",
    "entry_date",
    "entry_price",
    "exit_date",
    "exit_price",
    "last_date",
    "last_price",
    "stop_loss_price",
    "take_profit_price",
    "holding_days",
    "return_pct",
    "status",
    "reason",
]


def build_signal_trade_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """组装字段稳定的独立信号记录。"""

    return pd.DataFrame(rows, columns=SIGNAL_TRADE_COLUMNS)


@dataclass(slots=True)
class SignalBacktestResult:
    """信号回测记录及摘要信息。"""

    trades: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=SIGNAL_TRADE_COLUMNS)
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        """统计全部独立信号的收益表现。"""

        trades = self.trades
        qualified_count = int(self.metadata.get("qualified_signal_count", 0))
        base = {
            "strategy": self.metadata.get("strategy"),
            "start_date": self.metadata.get("start_date"),
            "end_date": self.metadata.get("end_date"),
            "signal_days": int(self.metadata.get("signal_days", 0)),
            "qualified_signal_count": qualified_count,
        }
        if trades.empty:
            return {
                **base,
                "executable_signal_count": 0,
                "skipped_signal_count": qualified_count,
                "closed_signal_count": 0,
                "open_signal_count": 0,
                "positive_signal_count": 0,
                "positive_signal_rate": 0.0,
                "win_rate": 0.0,
                "average_return": 0.0,
                "median_return": 0.0,
                "best_return": 0.0,
                "worst_return": 0.0,
                "average_holding_days": 0.0,
                "exit_reason_counts": {},
            }

        returns = pd.to_numeric(trades["return_pct"], errors="coerce").dropna()
        holding_days = pd.to_numeric(trades["holding_days"], errors="coerce").dropna()
        closed = trades[trades["status"] == "closed"]
        closed_returns = pd.to_numeric(
            closed["return_pct"], errors="coerce"
        ).dropna()
        positive_count = int((returns > 0).sum())
        closed_positive_count = int((closed_returns > 0).sum())
        executable_count = len(trades)

        return {
            **base,
            "executable_signal_count": executable_count,
            "skipped_signal_count": max(0, qualified_count - executable_count),
            "closed_signal_count": len(closed),
            "open_signal_count": int((trades["status"] == "open").sum()),
            "positive_signal_count": positive_count,
            "positive_signal_rate": (
                positive_count / len(returns) if len(returns) else 0.0
            ),
            "win_rate": (
                closed_positive_count / len(closed_returns)
                if len(closed_returns)
                else 0.0
            ),
            "average_return": float(returns.mean()) if len(returns) else 0.0,
            "median_return": float(returns.median()) if len(returns) else 0.0,
            "best_return": float(returns.max()) if len(returns) else 0.0,
            "worst_return": float(returns.min()) if len(returns) else 0.0,
            "average_holding_days": (
                float(holding_days.mean()) if len(holding_days) else 0.0
            ),
            "exit_reason_counts": {
                str(reason): int(count)
                for reason, count in trades["reason"].value_counts().items()
            },
        }
