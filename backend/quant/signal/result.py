"""组装选股信号接口返回结果。"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .registry import find_signal


def format_signal_result(
    signal_id: str,
    selected_stocks: pd.DataFrame,
    *,
    limit: int,
) -> dict[str, object]:
    limited_stocks = selected_stocks.head(limit)

    items = json.loads(
        limited_stocks.to_json(
            orient="records",
            date_format="iso",
            date_unit="s",
            double_precision=15,
        )
    )

    # 两阶段策略优先使用确认日；其他策略仍使用 latest_date。
    date_column = (
        "confirm_date"
        if "confirm_date" in limited_stocks.columns
        else "latest_date"
    )
    latest_date = (
        limited_stocks[date_column].max().date().isoformat()
        if not limited_stocks.empty and date_column in limited_stocks.columns
        else None
    )

    return {
        "signal": find_signal(signal_id),
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
            timespec="seconds"
        ),
        "trade_date": latest_date,
        "count": len(selected_stocks),
        "items": items,
    }
