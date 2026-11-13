"""组装选股信号接口返回结果。"""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from backend.app.config.config import TIMEZONE

from .registry import find_signal


def format_signal_result(
    signal_id: str,
    selected_stocks: pd.DataFrame,
    *,
    limit: int | None = None,
) -> dict[str, object]:
    selected_stocks = selected_stocks.copy()
    date_column = "confirm_date" if "confirm_date" in selected_stocks else "latest_date"
    latest_date = None
    stock_count = 0
    if not selected_stocks.empty:
        dates = pd.to_datetime(selected_stocks[date_column])
        selected_stocks["signal_date"] = dates.dt.strftime("%Y-%m-%d")
        latest_date = dates.max().date().isoformat()
        stock_count = selected_stocks["symbol"].nunique()
        selected_stocks = selected_stocks.sort_values("signal_date", ascending=False, kind="stable")

    limited_stocks = selected_stocks if limit is None else selected_stocks.head(limit)
    items = json.loads(
        limited_stocks.to_json(
            orient="records",
            date_format="iso",
            date_unit="s",
            double_precision=15,
        )
    )

    return {
        "signal": find_signal(signal_id),
        "generated_at": datetime.now(TIMEZONE).isoformat(
            timespec="seconds"
        ),
        "trade_date": latest_date,
        "count": len(selected_stocks),
        "stock_count": stock_count,
        "items": items,
    }
