"""成交量因子。"""

from __future__ import annotations

import pandas as pd


def calculate_volume_ratio_5d(df: pd.DataFrame) -> pd.DataFrame:
    """计算当日成交量相对最近 5 日平均成交量的倍数。"""

    result = df.copy()
    volume_ma5 = result["volume"].rolling(5).mean()
    result["volume_ratio_5d"] = result["volume"] / volume_ma5
    return result

