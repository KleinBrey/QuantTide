"""成交量因子。"""

from __future__ import annotations

import pandas as pd


def calculate_volume_ratio(
    df: pd.DataFrame,
    recent_days: int = 1,
    previous_days: int = 20,
) -> pd.DataFrame:
    """计算最近 N 日均量相对之前 M 日均量的倍数。"""

    result = df.copy()

    recent_avg_volume = result["volume"].rolling(recent_days).mean()

    previous_avg_volume = (
        result["volume"].shift(recent_days).rolling(previous_days).mean()
    )

    result["volume_ratio"] = recent_avg_volume / previous_avg_volume

    return result
