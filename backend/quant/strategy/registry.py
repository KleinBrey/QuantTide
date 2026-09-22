"""策略配置和执行入口。"""

import json
from pathlib import Path

from .implementations.panic_reversal_v import run_strategy as run_panic_reversal
from .implementations.breakout_pullback_n import (
    run_strategy as run_strong_breakout_pullback,
)
from .implementations.today_emotion_reversal import (
    run_strategy as run_today_emotion_reversal,
)
from .implementations.today_volume_breakout import (
    run_strategy as run_today_volume_breakout,
)
from .implementations.recent_volume_breakout import (
    run_strategy as run_recent_volume_breakout,
)
from .implementations.second_rebound_short import (
    run_strategy as run_second_rebound_short,
)

CONFIG_PATH = Path(__file__).with_name("strategies.json")

STRATEGY_EXECUTORS = {
    "panic-reversal": run_panic_reversal,
    "second-rebound-short": run_second_rebound_short,
    "strong-breakout-pullback": run_strong_breakout_pullback,
    "recent_volume_breakout": run_recent_volume_breakout,
    "today_volume_breakout": run_today_volume_breakout,
    "today_emotion_reversal": run_today_emotion_reversal,
}


def strategy_list() -> list[dict[str, object]]:
    """策略列表"""
    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        return json.load(config_file)["strategies"]


def find_strategy(strategy_id: str) -> dict[str, object]:
    """查询策略"""
    for strategy in strategy_list():
        if strategy["id"] == strategy_id:
            return strategy
    raise KeyError(strategy_id)


def execute_strategy(strategy_id: str, **inputs):
    """执行策略"""
    return STRATEGY_EXECUTORS[strategy_id](**inputs)
