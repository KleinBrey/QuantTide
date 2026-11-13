"""历史扫描公共工具：日期规范化、前置行情裁剪、按日匹配快照。

不注册策略，也不决定策略需要多少历史或使用哪些筛选条件。
"""

from collections.abc import Callable, Iterable
from datetime import date
from typing import Protocol

import pandas as pd

from backend.quant.stock.universe import build_snapshot_lookup

DateLike = date | str | pd.Timestamp


class RangeSignal(Protocol):
    """所有信号策略共同的区间扫描接口。"""

    def scan_range(
        self,
        trade_dates: Iterable[DateLike],
        historical_stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        historical_hot: pd.DataFrame,
        historical_basic: pd.DataFrame,
    ) -> pd.DataFrame: ...


def normalize_trade_dates(trade_dates: Iterable[DateLike]) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(trade_dates))).normalize().drop_duplicates().sort_values()


def trim_history_bars(
    daily_bars: pd.DataFrame, trade_dates: pd.DatetimeIndex, *, lookback_rows: int,
) -> pd.DataFrame:
    """保留扫描区间及每只股票区间前的指定行数，先排序再截取。"""
    if trade_dates.empty or daily_bars.empty:
        return daily_bars.iloc[:0].copy()
    bars = daily_bars.copy()
    bars['trade_date'] = pd.to_datetime(bars['trade_date'])
    bars = bars[bars.trade_date <= trade_dates.max()].sort_values(['symbol', 'trade_date'], kind='stable')
    prior = bars[bars.trade_date < trade_dates.min()].groupby('symbol', sort=False).tail(lookback_rows)
    return pd.concat([prior, bars[bars.trade_date >= trade_dates.min()]], ignore_index=True)


def select_by_snapshot(
    indicators: pd.DataFrame,
    historical_stocks: pd.DataFrame,
    historical_hot: pd.DataFrame,
    historical_basic: pd.DataFrame,
    select: Callable[[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame], pd.DataFrame],
    *,
    date_column: str = 'latest_date',
) -> pd.DataFrame:
    """仅对已计算的指标匹配当日可见快照，具体筛选由策略传入。"""
    if indicators.empty:
        return pd.DataFrame()
    stocks_as_of = build_snapshot_lookup(historical_stocks)
    hot_as_of = build_snapshot_lookup(historical_hot)
    basic_as_of = build_snapshot_lookup(historical_basic)
    results = []
    for day, rows in indicators.groupby(date_column, sort=True):
        stocks = stocks_as_of(day)
        if stocks.empty:
            continue
        result = select(rows, stocks, basic_as_of(day), hot_as_of(day))
        if not result.empty:
            results.append(result)
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()
