"""信号配置和形态识别入口。"""

import json
from pathlib import Path

from backend.quant.signal.patterns.breakout_pullback_n import (
    run_signal as run_strong_breakout_pullback,
)
from backend.quant.signal.patterns.panic_reversal_v import (
    run_signal as run_panic_reversal,
)
from backend.quant.signal.patterns.recent_volume_breakout import (
    run_signal as run_recent_volume_breakout,
)
from backend.quant.signal.patterns.second_rebound_short import (
    run_signal as run_second_rebound_short,
)
from backend.quant.signal.patterns.today_confirmed_breakout import (
    run_signal as run_confirmed_volume_breakout,
)
from backend.quant.signal.patterns.today_emotion_reversal import (
    run_signal as run_today_emotion_reversal,
)
from backend.quant.signal.patterns.today_volume_breakout import (
    run_signal as run_today_volume_breakout,
)

CONFIG_PATH = Path(__file__).with_name("signals.json")

SIGNAL_EXECUTORS = {
    "panic-reversal": run_panic_reversal,
    "second-rebound-short": run_second_rebound_short,
    "strong-breakout-pullback": run_strong_breakout_pullback,
    "recent_volume_breakout": run_recent_volume_breakout,
    "today_volume_breakout": run_today_volume_breakout,
    "today_emotion_reversal": run_today_emotion_reversal,
    "confirmed_volume_breakout": run_confirmed_volume_breakout,
}


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
