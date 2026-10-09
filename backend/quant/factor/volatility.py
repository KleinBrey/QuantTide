"""波动率因子。"""

from __future__ import annotations

import pandas as pd


def calculate_volatility_20d(df: pd.DataFrame) -> pd.DataFrame:
    """计算最近 20 个单日收益率的标准差。"""

    result = df.copy()
    daily_return = result["close"].pct_change(fill_method=None)
    result["volatility_20d"] = daily_return.rolling(20).std()
    return result

