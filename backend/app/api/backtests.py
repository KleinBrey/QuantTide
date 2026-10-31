"""回测策略列表与策略回测执行。"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from backend.quant.backtest.engine import BacktestConfig, BacktestEngine
from backend.quant.backtest.result import format_backtest_result
from backend.quant.strategy.registry import STRATEGIES, strategy_info, strategy_list

from .dependencies import DailyBasicRepo, DailyHotRepo, DailyRepository, DailyStockRepo

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/backtests/strategies")
async def backtest_strategies() -> list[dict[str, str]]:
    """只列出已实现入场与退出规则的可回测策略。"""

    return strategy_list()



@router.get("/backtests/{strategy_id}")
async def strategy_backtest(
    strategy_id: str,
    daily_stock_repository: DailyStockRepo,
    daily_repository: DailyRepository,
    daily_basic_repository: DailyBasicRepo,
    daily_hot_repository: DailyHotRepo,
    start_date: Annotated[
        date | None,
        Query(description="回测开始日期，默认按回看月数计算"),
    ] = None,
    end_date: Annotated[
        date | None,
        Query(description="回测结束日期，默认使用最新交易日"),
    ] = None,
    lookback_months: Annotated[int, Query(ge=1, le=60)] = 12,
    max_positions: Annotated[int, Query(ge=1, le=100)] = 20,
    max_position_pct: Annotated[float, Query(gt=0, le=1, allow_inf_nan=False)] = 0.05,
    initial_cash: Annotated[float, Query(gt=0, allow_inf_nan=False)] = 1_000_000.0,
) -> dict[str, object]:
    """按策略 ID 执行回测，返回绩效和逐笔交易记录。"""

    strategy_class = STRATEGIES.get(strategy_id)
    if strategy_class is None:
        raise HTTPException(status_code=404, detail="回测策略不存在")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="回测开始日期不能晚于结束日期")

    config = BacktestConfig(
        initial_cash=initial_cash,
        start_date=start_date,
        end_date=end_date,
        lookback_months=lookback_months,
        max_positions=max_positions,
        max_position_pct=max_position_pct,
    )

    def run_backtest():
        return BacktestEngine(strategy_class(), config).run(
            historical_stocks=daily_stock_repository.get_table_data(),
            daily_bars=daily_repository.get_table_data(),
            historical_hot=daily_hot_repository.get_table_data(),
            historical_basic=daily_basic_repository.get_table_data(),
        )

    try:
        result = await run_in_threadpool(run_backtest)
    except Exception as error:
        logger.exception("执行回测 %s 失败", strategy_id)
        raise HTTPException(
            status_code=500,
            detail=f"策略回测失败：{error}",
        ) from error

    return format_backtest_result(
        result,
        strategy=strategy_info(strategy_class),
    )

