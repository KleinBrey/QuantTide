"""回测账户的现金、持仓和总资产。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import isfinite

from .position import Position


@dataclass(slots=True)
class Account:
    """只做多账户；MVP 不允许融资、融券或同一股票重复建仓。"""

    initial_cash: float
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if not isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("初始资金必须是大于 0 的有限数")
        self.cash = float(self.initial_cash)

    def buy(
        self,
        *,
        symbol: str,
        name: str,
        quantity: int,
        price: float,
        fee: float,
        stop_loss_price: float,
        take_profit_price: float,
        signal_date: date,
        trade_date: date,
    ) -> Position:
        """买入一只当前未持有的股票。"""

        if symbol in self.positions:
            raise ValueError(f"已持有 {symbol}，MVP 不支持加仓")
        if quantity <= 0 or price <= 0 or fee < 0:
            raise ValueError("买入数量和价格必须大于 0，费用不能为负")
        if not 0 < stop_loss_price < price < take_profit_price:
            raise ValueError("必须满足止损价 < 买入价 < 止盈价")

        gross_amount = quantity * price
        total_cost = gross_amount + fee
        if total_cost > self.cash + 1e-8:
            raise ValueError(f"现金不足：需要 {total_cost:.2f}，可用 {self.cash:.2f}")

        self.cash -= total_cost
        position = Position(
            symbol=symbol,
            name=name,
            quantity=quantity,
            entry_price=price,
            cost_price=total_cost / quantity,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            signal_date=signal_date,
            opened_at=trade_date,
        )
        self.positions[symbol] = position
        return position

    def sell(
        self,
        *,
        symbol: str,
        price: float,
        fee: float,
    ) -> tuple[Position, float]:
        """全部卖出一只股票，返回原持仓和已实现盈亏。"""

        if price <= 0 or fee < 0:
            raise ValueError("卖出价格必须大于 0，费用不能为负")

        position = self.positions.pop(symbol)
        net_proceeds = position.quantity * price - fee
        self.cash += net_proceeds
        realized_pnl = net_proceeds - position.cost_basis
        return position, realized_pnl

    def market_value(self, prices: dict[str, float]) -> float:
        """按最新可用价格计算持仓市值。"""

        value = 0.0
        for symbol, position in self.positions.items():
            price = prices.get(symbol, position.cost_price)
            value += position.market_value(price)
        return value

    def total_equity(self, prices: dict[str, float]) -> float:
        """计算现金与持仓市值之和。"""

        return self.cash + self.market_value(prices)
