"""按时点匹配完整股票池快照，不把退市成员从旧快照拼回新股票池。"""

import pandas as pd


def match_stock_snapshots(
    candidates: pd.DataFrame, stocks_history: pd.DataFrame, *, date_column: str
) -> pd.DataFrame:
    """先向前匹配整日快照日期，再按代码取当日资料；缺历史则排除。"""
    required = ["trade_date", "symbol", "name", "exchange", "market"]
    if "trade_date" not in stocks_history.columns:
        raise ValueError("股票池必须包含 trade_date，不能使用无日期的当前股票池回测")
    history = stocks_history[required].copy()
    history["trade_date"] = pd.to_datetime(history["trade_date"], errors="raise").dt.normalize()
    if history["trade_date"].isna().any():
        raise ValueError("股票池快照日期不能为空")
    history = history.rename(columns={"trade_date": "stock_snapshot_date"})
    snapshots = history[["stock_snapshot_date"]].drop_duplicates().sort_values("stock_snapshot_date")
    matched = pd.merge_asof(
        candidates.sort_values(date_column), snapshots,
        left_on=date_column, right_on="stock_snapshot_date", direction="backward",
    )
    return matched.merge(history, on=["stock_snapshot_date", "symbol"], how="inner",
                         validate="many_to_one").drop(columns="stock_snapshot_date")
