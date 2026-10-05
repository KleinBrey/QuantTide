"""可回测策略；按注册顺序展示，首个策略为默认策略。"""

from .base import Strategy
from .today_confirmed_breakout import TodayConfirmedBreakoutStrategy

STRATEGIES: dict[str, type[Strategy]] = {
    TodayConfirmedBreakoutStrategy.id: TodayConfirmedBreakoutStrategy,
}


def strategy_info(strategy: type[Strategy]) -> dict[str, str]:
    return {
        "id": strategy.id,
        "name": strategy.name,
        "description": strategy.description,
    }


def strategy_list() -> list[dict[str, str]]:
    return [strategy_info(strategy) for strategy in STRATEGIES.values()]
