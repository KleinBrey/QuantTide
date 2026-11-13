"""信号配置和形态识别入口。"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.quant.signal.patterns.breakout_pullback_n import (
    StrongBreakoutPullbackPattern,
    run_signal as run_strong_breakout_pullback,
)
from backend.quant.signal.patterns.panic_reversal_v import (
    PanicReversalVPattern,
    run_signal as run_panic_reversal,
)
from backend.quant.signal.patterns.recent_volume_breakout import (
    VolumeBreakoutPattern,
    run_signal as run_recent_volume_breakout,
)
from backend.quant.signal.patterns.second_rebound_short import (
    SecondReboundShortPattern,
    run_signal as run_second_rebound_short,
)
from backend.quant.signal.patterns.today_confirmed_breakout import (
    TodayConfirmedBreakoutPattern,
    run_signal as run_confirmed_volume_breakout,
)
from backend.quant.signal.patterns.today_emotion_reversal import (
    TodayEmotionReversalPattern,
    run_signal as run_today_emotion_reversal,
)
from backend.quant.signal.patterns.today_volume_breakout import (
    TodayVolumeBreakoutPattern,
    run_signal as run_today_volume_breakout,
)

from .range_utils import RangeSignal

CONFIG_PATH = Path(__file__).with_name("signals.json")


@dataclass(frozen=True)
class SignalHandler:
    """一次注册单日入口与实现统一 scan_range 接口的策略类。"""

    latest: Callable
    range_factory: type[RangeSignal]


SIGNAL_HANDLERS = {
    "strong-breakout-pullback": SignalHandler(run_strong_breakout_pullback, StrongBreakoutPullbackPattern),
    "panic-reversal": SignalHandler(run_panic_reversal, PanicReversalVPattern),
    "second-rebound-short": SignalHandler(run_second_rebound_short, SecondReboundShortPattern),
    "recent_volume_breakout": SignalHandler(run_recent_volume_breakout, VolumeBreakoutPattern),
    "today_volume_breakout": SignalHandler(run_today_volume_breakout, TodayVolumeBreakoutPattern),
    "today_emotion_reversal": SignalHandler(run_today_emotion_reversal, TodayEmotionReversalPattern),
    "confirmed_volume_breakout": SignalHandler(run_confirmed_volume_breakout, TodayConfirmedBreakoutPattern),
}

# 保留现有单日调用接口，两个入口从同一份注册信息生成。
SIGNAL_EXECUTORS = {key: handler.latest for key, handler in SIGNAL_HANDLERS.items()}
SIGNAL_PATTERNS = {key: handler.range_factory for key, handler in SIGNAL_HANDLERS.items()}


def signal_list() -> list[dict[str, object]]:
    """返回已注册的选股信号。"""

    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        return json.load(config_file)["signals"]


def find_signal(signal_id: str) -> dict[str, object]:
    """按 ID 查询信号配置。"""

    for signal in signal_list():
        if signal["id"] == signal_id:
            return signal
    raise KeyError(signal_id)


def execute_signal(signal_id: str, **inputs):
    """运行指定的形态识别器。"""

    return SIGNAL_EXECUTORS[signal_id](**inputs)
