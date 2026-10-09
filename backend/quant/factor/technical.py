"""技术指标因子。"""

from __future__ import annotations

import pandas as pd


def calculate_distance_ma20(df: pd.DataFrame) -> pd.DataFrame:
    """计算收盘价偏离 20 日均线的比例。"""

    result = df.copy()
    moving_average_20d = result["close"].rolling(20).mean()
    result["distance_ma20"] = result["close"] / moving_average_20d - 1
    return result

