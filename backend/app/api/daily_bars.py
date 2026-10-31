"""按市场、代码和日期范围查询日 K 线。"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from backend.app.schemas import DailyBar
from backend.app.utils.symbol import normalize_daily_bar_symbol

from .dependencies import (
    CryptoMarketServiceDep,
    DailyRepository,
    FuturesRepository,
    HKDailyRepository,
    USDailyRepository,
)

router = APIRouter()


@router.get("/crypto/daily-bars/{symbol}", tags=["加密货币"], name="daily_bars")
def crypto_daily_bars(symbol: str, service: CryptoMarketServiceDep) -> list[dict]:
    return service.repository.get_daily_bars(symbol.strip().upper())


@router.get("/daily-bars", response_model=list[DailyBar])
def daily_bars(
    repository: DailyRepository,
    hk_repository: HKDailyRepository,
    us_repository: USDailyRepository,
    futures_repository: FuturesRepository,
    symbol: Annotated[
        str,
        Query(description="股票代码，例如 600519.SH、0700.HK 或 NVDA.O"),
    ],
    start: Annotated[
        date,
        Query(description="开始日期，格式 YYYY-MM-DD，包含当天"),
    ],
    end: Annotated[
        date,
        Query(description="结束日期，格式 YYYY-MM-DD，包含当天"),
    ],
    market: Annotated[
        Literal["a-share", "hk-share", "us-share", "futures"],
        Query(description="日 K 所在市场数据库"),
    ] = "a-share",
) -> list[dict]:
    """按市场从对应 DuckDB 查询指定日期范围内的日 K 线。"""

    if start > end:
        raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")

    try:
        normalized_symbol = normalize_daily_bar_symbol(symbol, market)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    repositories = {
        "a-share": repository,
        "hk-share": hk_repository,
        "us-share": us_repository,
        "futures": futures_repository,
    }
    daily_bar_table = repositories[market].get_by_symbol_and_date_range(
        normalized_symbol,
        start,
        end,
    )

    records = daily_bar_table.to_dict(orient="records")

    return records

