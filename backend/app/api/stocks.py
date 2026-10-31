"""股票列表、港美股股票池管理及加密货币交易对查询。"""

from __future__ import annotations

from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from backend.app.jobs.tasks import database_sync_lock
from backend.app.schemas import AddMarketStock, GlobalStock, Stock
from backend.app.utils.symbol import normalize_daily_bar_symbol

from .dependencies import (
    CNMarketServiceDep,
    CryptoMarketServiceDep,
    DailyStockRepo,
    HKStockListRepository,
    USStockListRepository,
    WatchlistServiceDep,
)

router = APIRouter()


@router.get("/crypto/symbols", tags=["加密货币"], name="symbols")
def crypto_symbols(service: CryptoMarketServiceDep) -> list[dict]:
    return service.repository.list_symbols()


@router.get("/stocks-list", response_model=list[Stock])
def stocks(
    repository: DailyStockRepo,
) -> list[dict]:
    stock_table = repository.get_latest_data().head(100)

    # FastAPI 不能直接把 DataFrame 当成“股票列表”返回。
    # orient="records" 会把每一行转换成一个字典，最终得到：
    # [{"symbol": "000001.SZ", "name": "平安银行", ...}, ...]
    stock_list = stock_table.to_dict(orient="records")
    return stock_list



@router.get("/market-stocks", response_model=list[GlobalStock])
def market_stocks(
    watchlist_service: WatchlistServiceDep,
    market: Annotated[
        Literal["hk_stock", "us_stock"],
        Query(description="股票池所在的市场数据库"),
    ],
) -> list[dict]:
    """返回 SQLite 默认股票池成员，并从 DuckDB 补充基础信息。"""

    pool = watchlist_service.repository.get_pool("HK" if market == "hk_stock" else "US")
    return watchlist_service.list_items(pool["id"])



@router.post("/market-stocks", response_model=GlobalStock, status_code=201)
def add_market_stock(
    stock: AddMarketStock,
    hk_repository: HKStockListRepository,
    us_repository: USStockListRepository,
    watchlist_service: WatchlistServiceDep,
) -> dict:
    """添加股票池记录；K 线仍由已有的数据同步任务获取。"""

    try:
        symbol = normalize_daily_bar_symbol(stock.symbol, stock.market)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    name = stock.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="股票名称不能为空")
    repository = hk_repository if stock.market == "hk_stock" else us_repository
    market = "HK" if stock.market == "hk_stock" else "US"
    pool = watchlist_service.repository.get_pool(market)
    with database_sync_lock:
        if any(
            item["symbol"] == symbol
            for item in watchlist_service.repository.list_items(pool["id"])
        ):
            raise HTTPException(status_code=409, detail="该股票已在列表中")
        if symbol not in repository.get_table_data()["symbol"].values:
            repository.upsert_stocks(
                pd.DataFrame([{"symbol": symbol, "name": name, "source": "Manual"}])
            )
        watchlist_service.repository.add_item(pool["id"], market, symbol)
        rows = repository.get_table_data()
        return rows.loc[rows["symbol"] == symbol].to_dict(orient="records")[0]



@router.delete("/market-stocks")
def delete_market_stock(
    watchlist_service: WatchlistServiceDep,
    market: Literal["hk_stock", "us_stock"],
    symbol: str,
) -> dict[str, str]:
    """仅从股票池删除，不删除历史 K 线。"""

    try:
        normalized = normalize_daily_bar_symbol(symbol, market)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    with database_sync_lock:
        market_code = "HK" if market == "hk_stock" else "US"
        pool = watchlist_service.repository.get_pool(market_code)
        watchlist_service.repository.remove_stock(pool["id"], market_code, normalized)
    return {"status": "success"}



@router.post("/stocks-list")
def update_daily_stocks(cn_market_service: CNMarketServiceDep) -> dict[str, str]:
    """从数据源获取最新股票列表，并保存到本地数据库。"""

    cn_market_service.update_daily_stocks()

    # 只有上面的更新操作没有抛出异常时，才会执行到这里。
    return {
        "status": "success",
        "message": "股票列表更新成功",
    }

