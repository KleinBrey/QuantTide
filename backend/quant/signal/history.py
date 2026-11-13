"""历史信号入口：校验日期，通过注册表分发给策略。"""

import pandas as pd

from .registry import SIGNAL_PATTERNS


def scan_signal_range(
    signal_id: str,
    *,
    start_date,
    end_date,
    daily_bars: pd.DataFrame,
    historical_stocks: pd.DataFrame,
    historical_hot: pd.DataFrame,
    historical_basic: pd.DataFrame,
) -> pd.DataFrame:
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    if pd.isna(start) or pd.isna(end) or start > end:
        raise ValueError("扫描日期必须有效，且开始日期不能晚于结束日期")
    pattern = SIGNAL_PATTERNS[signal_id]()
    dates = pd.to_datetime(daily_bars["trade_date"])
    trade_dates = pd.DatetimeIndex(dates[dates.between(start, end)].unique()).sort_values()
    if trade_dates.empty:
        return pd.DataFrame()
    return pattern.scan_range(
        trade_dates=trade_dates,
        historical_stocks=historical_stocks,
        daily_bars=daily_bars,
        historical_hot=historical_hot,
        historical_basic=historical_basic,
    )
