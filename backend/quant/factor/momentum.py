"""动量因子。"""

from __future__ import annotations

import pandas as pd


def calculate_momentum_5d(df: pd.DataFrame) -> pd.DataFrame:
    """计算 5 日动量：今日收盘价 / 5 个交易日前收盘价 - 1。"""

    result = df.copy()
    result["momentum_5d"] = result["close"] / result["close"].shift(5) - 1
    return result


def calculate_momentum_20d(df: pd.DataFrame) -> pd.DataFrame:
    """计算 20 日动量：今日收盘价 / 20 个交易日前收盘价 - 1。"""

    result = df.copy()
    result["momentum_20d"] = result["close"] / result["close"].shift(20) - 1
    return result

