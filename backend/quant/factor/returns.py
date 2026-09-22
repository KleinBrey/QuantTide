"""收益率因子。"""

from __future__ import annotations

import pandas as pd


def calculate_return_1d(df: pd.DataFrame) -> pd.DataFrame:
    """计算单日收益率：今日收盘价 / 昨日收盘价 - 1。"""

    result = df.copy()
    result["return_1d"] = result["close"].pct_change(fill_method=None)
    return result

