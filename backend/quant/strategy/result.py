"""组装策略接口返回结果。"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .registry import find_strategy


def format_strategy_result(
    strategy_id: str,
    selected_stocks: pd.DataFrame,
    *,
    limit: int,
) -> dict[str, object]:
    limited_stocks = selected_stocks.head(limit)

    # 序列化，反序列化数据
    items = json.loads(
        limited_stocks.to_json(
            orient="records",
            date_format="iso",
            date_unit="s",
            double_precision=15,
        )
    )

    # 获取最新日期
    date_column = (
        "latest_date"
        if "latest_date" in limited_stocks.columns
        else "entry_date"
    )
    latest_date = (
        limited_stocks[date_column].max().date().isoformat()
        if not limited_stocks.empty and date_column in limited_stocks.columns
        else None
    )

    return {
        "strategy": find_strategy(strategy_id),
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
            timespec="seconds"
        ),
        "trade_date": latest_date,
        "count": len(selected_stocks),
        "items": items,
    }
