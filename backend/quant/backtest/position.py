"""单只股票持仓。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Position:
    """记录一只股票的数量和含买入费用成本价。"""

    symbol: str
    name: str
    quantity: int
    entry_price: float
    cost_price: float
    stop_loss_price: float
    take_profit_price: float
    signal_date: date
    opened_at: date

    @property
    def cost_basis(self) -> float:
        """持仓总成本。"""

        return self.quantity * self.cost_price

    def market_value(self, price: float) -> float:
        """按给定价格计算市值。"""

        return self.quantity * price
