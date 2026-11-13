"""选股信号列表与信号执行结果。"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from backend.quant.signal.history import scan_signal_range
from backend.quant.signal.registry import SIGNAL_EXECUTORS, signal_list
from backend.quant.signal.result import format_signal_result

from ..config.config import TIMEZONE
from .dependencies import DailyBasicRepo, DailyHotRepo, DailyRepository, DailyStockRepo

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/signals")
def signals() -> dict[str, list[dict[str, object]]]:
    """返回选股信号列表。"""

    return {"items": signal_list()}


@router.get("/signals/{signal_id}")
def signal_results(
    signal_id: str,
    daily_stock_repository: DailyStockRepo,
    daily_repository: DailyRepository,
    daily_basic_repository: DailyBasicRepo,
    daily_hot_repository: DailyHotRepo,
    mode: Literal["today", "history"] = "history",
    start_date: date | None = None,
    end_date: date | None = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
) -> dict[str, object]:
    """运行指定形态识别器并返回命中结果。"""

    if signal_id not in SIGNAL_EXECUTORS:
        raise HTTPException(status_code=404, detail="该信号不存在")

    if mode == "history":
        if start_date is None or end_date is None:
            raise HTTPException(
                status_code=422, detail="历史扫描必须提供开始日期和结束日期"
            )
        if start_date > end_date:
            raise HTTPException(status_code=422, detail="扫描开始日期不能晚于结束日期")

    try:
        daily_bars = daily_repository.get_table_data()
        if mode == "today":
            today = datetime.now(TIMEZONE).date()
            # 周末、节假日和当日日线尚未同步时，使用本地最近一个交易日。
            dates = pd.to_datetime(daily_bars["trade_date"])
            available = dates[dates <= pd.Timestamp(today)]
            scan_date = available.max().date() if not available.empty else today
            start_date = end_date = scan_date
        selected_stocks = scan_signal_range(
            signal_id,
            start_date=start_date,
            end_date=end_date,
            historical_stocks=daily_stock_repository.get_table_data(),
            daily_bars=daily_bars,
            historical_hot=daily_hot_repository.get_table_data(),
            historical_basic=daily_basic_repository.get_table_data(),
        )
    except Exception as error:
        logger.exception("执行信号 %s 失败", signal_id)
        raise HTTPException(
            status_code=500,
            detail=f"信号执行失败：{error}",
        ) from error

    result = format_signal_result(signal_id, selected_stocks, limit=limit)
    return {
        **result,
        "mode": mode,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
