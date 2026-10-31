"""选股信号列表与信号执行结果。"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from backend.quant.signal.registry import SIGNAL_EXECUTORS, execute_signal, signal_list
from backend.quant.signal.result import format_signal_result

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
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, object]:
    """运行指定形态识别器并返回命中结果。"""

    if signal_id not in SIGNAL_EXECUTORS:
        raise HTTPException(status_code=404, detail="该信号不存在")

    try:
        selected_stocks = execute_signal(
            signal_id,
            latest_stocks=daily_stock_repository.get_latest_data(),
            daily_bars=daily_repository.get_table_data(),
            latest_hot=daily_hot_repository.get_latest_data(),
            latest_basic=daily_basic_repository.get_latest_data(),
        )
    except Exception as error:
        logger.exception("执行信号 %s 失败", signal_id)
        raise HTTPException(
            status_code=500,
            detail=f"信号执行失败：{error}",
        ) from error

    return format_signal_result(signal_id, selected_stocks, limit=limit)

