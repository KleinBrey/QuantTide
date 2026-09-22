"""基础量价因子及统一计算入口。"""

from __future__ import annotations

import pandas as pd

from .momentum import calculate_momentum_20d, calculate_momentum_5d
from .returns import calculate_return_1d
from .technical import calculate_distance_ma20
from .volatility import calculate_volatility_20d
from .volume import calculate_volume_ratio_5d

REQUIRED_COLUMNS = ["symbol", "trade_date", "close", "volume"]
FACTOR_COLUMNS = [
    "return_1d",
    "momentum_5d",
    "momentum_20d",
    "volume_ratio_5d",
    "volatility_20d",
    "distance_ma20",
]


def calculate_basic_factors(df: pd.DataFrame) -> pd.DataFrame:
    """按股票计算全部基础因子，不跨股票或使用未来数据。"""

    missing_columns = [
        column for column in REQUIRED_COLUMNS if column not in df.columns
    ]
    if missing_columns:
        raise ValueError(f"日 K 数据缺少字段：{', '.join(missing_columns)}")

    bars = df.copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise")
    bars["close"] = pd.to_numeric(bars["close"], errors="raise")
    bars["volume"] = pd.to_numeric(bars["volume"], errors="raise")

    if bars.empty:
        for column in FACTOR_COLUMNS:
            bars[column] = pd.Series(dtype="float64")
        return bars

    results = []
    for _, symbol_bars in bars.groupby("symbol", sort=False, dropna=False):
        result = symbol_bars.sort_values("trade_date").copy()
        result = calculate_return_1d(result)
        result = calculate_momentum_5d(result)
        result = calculate_momentum_20d(result)
        result = calculate_volume_ratio_5d(result)
        result = calculate_volatility_20d(result)
        result = calculate_distance_ma20(result)
        results.append(result)

    return (
        pd.concat(results)
        .sort_values(["symbol", "trade_date"])
        .reset_index(drop=True)
    )


__all__ = [
    "FACTOR_COLUMNS",
    "REQUIRED_COLUMNS",
    "calculate_basic_factors",
    "calculate_distance_ma20",
    "calculate_momentum_20d",
    "calculate_momentum_5d",
    "calculate_return_1d",
    "calculate_volatility_20d",
    "calculate_volume_ratio_5d",
]

