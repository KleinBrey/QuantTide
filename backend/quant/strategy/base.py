"""日频策略约定；Protocol 只描述接口，策略无需继承它。"""

from typing import Protocol

import pandas as pd


class Strategy(Protocol):
    id: str
    name: str
    description: str

    def generate_entries_range(
        self,
        trade_dates: pd.DatetimeIndex,
        stocks: pd.DataFrame,
        daily_bars: pd.DataFrame,
        hot_stocks: pd.DataFrame,
        stock_daily_basic: pd.DataFrame,
    ) -> pd.DataFrame:
        """返回 symbol、name、entry_date、signal_date、selection_rank、entry_reason。

        日期用 pandas Timestamp；同一股票每天至多一条候选。
        stop_loss_price、take_profit_price 是可选附加列。
        每个交易日只使用当天及以前的数据计算入场信号。
        """
        ...

    def find_exits(
        self, entries: pd.DataFrame, daily_bars: pd.DataFrame
    ) -> pd.DataFrame:
        """返回 symbol、entry_date、exit_date、exit_reason，无退出则不返回该笔。

        为每个候选计算第一个退出日，日期为 Timestamp。
        退出日须晚于入场日且有可成交行情；指标只使用退出日及此前数据。
        """
        ...

    def assumptions(self) -> list[str]:
        """返回策略规则说明；没有补充说明时返回空列表。"""
        ...
