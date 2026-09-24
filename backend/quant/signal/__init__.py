"""选股信号注册与结果输出模块。"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SIGNAL_EXECUTORS",
    "execute_signal",
    "find_signal",
    "signal_list",
]


def __getattr__(name: str) -> Any:
    """延迟加载注册表，避免导入信号包时预先加载全部形态实现。"""

    if name in __all__:
        from . import registry

        return getattr(registry, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
