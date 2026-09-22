"""股票策略模块。"""

from __future__ import annotations

from typing import Any

__all__ = [
    "STRATEGY_EXECUTORS",
    "execute_strategy",
    "find_strategy",
    "strategy_list",
]


def __getattr__(name: str) -> Any:
    """延迟加载注册表，避免执行单个策略模块时被预先导入。"""

    if name in __all__:
        from . import registry

        return getattr(registry, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
