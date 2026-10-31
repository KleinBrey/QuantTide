"""A 股、港股和美股热度榜查询。"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter

from backend.app.schemas import HotStock

from .dependencies import CNMarketServiceDep, HKMarketServiceDep, USMarketServiceDep

router = APIRouter()


@router.get("/hot-stock", response_model=list[HotStock])
def hot_stock(cn_market_service: CNMarketServiceDep, count: int = 100) -> list[dict]:
    """返回最新 A 股热度榜；数据库缓存超过两小时时自动同步。"""

    hot_stock_table = cn_market_service.get_hot_stock().head(count)
    # 将 pandas 的 NaN/NaT 转为 None，确保可选字段能被 JSON 正确编码。
    hot_stock_table = hot_stock_table.astype(object).where(
        pd.notna(hot_stock_table),
        None,
    )
    return hot_stock_table.to_dict(orient="records")



@router.get("/hk-hot-stock", response_model=list[HotStock])
def hk_hot_stock(hk_market_service: HKMarketServiceDep, count: int = 50) -> list[dict]:
    """返回最新港股热度榜；数据库缓存超过两小时时自动同步。"""

    hot_stock_table = hk_market_service.get_hot_stock().head(count)
    hot_stock_table = hot_stock_table.astype(object).where(
        pd.notna(hot_stock_table),
        None,
    )
    return hot_stock_table.to_dict(orient="records")



@router.get("/us-hot-stock", response_model=list[HotStock])
def us_hot_stock(us_market_service: USMarketServiceDep, count: int = 50) -> list[dict]:
    """返回最新美股热度榜；数据库缓存超过两小时时自动同步。"""

    hot_stock_table = us_market_service.get_hot_stock().head(count)
    hot_stock_table = hot_stock_table.astype(object).where(
        pd.notna(hot_stock_table),
        None,
    )
    return hot_stock_table.to_dict(orient="records")

