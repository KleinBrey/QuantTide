"""加密货币页面接口：本地查询与手动同步。"""

from typing import Annotated

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from ..jobs.tasks import database_sync_lock
from ..services.crypto_market_service import CryptoMarketService

router = APIRouter(prefix="/crypto", tags=["加密货币"])


def get_service(request: Request) -> CryptoMarketService:
    return request.app.state.crypto_market_service


Service = Annotated[CryptoMarketService, Depends(get_service)]


class SyncCryptoBars(BaseModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]{2,30}$")
    days: int = Field(default=365, ge=1, le=1000)

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper() if isinstance(value, str) else value


@router.get("/symbols")
def symbols(service: Service) -> list[dict]:
    return service.repository.list_symbols()


@router.get("/daily-bars/{symbol}")
def daily_bars(symbol: str, service: Service) -> list[dict]:
    return service.repository.get_daily_bars(symbol.strip().upper())


@router.post("/sync")
def sync_daily_bars(body: SyncCryptoBars, service: Service) -> dict:
    if not database_sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有数据同步任务正在执行，请稍后重试")
    try:
        count = service.sync_daily_bars(body.symbol, body.days)
    except requests.RequestException as error:
        raise HTTPException(status_code=502, detail="行情获取失败，请检查交易对代码和网络后重试") from error
    finally:
        database_sync_lock.release()
    return {"symbol": body.symbol, "rows": count}
