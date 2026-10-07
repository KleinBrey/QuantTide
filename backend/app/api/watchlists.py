from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from backend.app.services.watchlist_service import WatchlistService
from .dependencies import get_watchlist_service

router = APIRouter(prefix='/watchlists', tags=['自选股'])
Service = Annotated[WatchlistService, Depends(get_watchlist_service)]
Market = Literal['CN', 'HK', 'US']


class GroupName(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError('分组名称不能为空')
        if value.strip().lower() == 'stock_pool':
            raise ValueError('stock_pool 为系统默认分组保留名称')
        return value.strip()


class CreateGroup(GroupName):
    market: Market | None = None


class AddItem(BaseModel):
    market: Market
    symbol: str = Field(min_length=1, max_length=32)


class Order(BaseModel):
    ids: list[int] = Field(max_length=10000)


@router.get('/stocks/search')
def search_stocks(service: Service, q: Annotated[str, Query(min_length=1, max_length=100)], market: Market | None = None,
                  limit: Annotated[int, Query(ge=1, le=100)] = 50):
    if not q.strip():
        raise HTTPException(status_code=422, detail='搜索内容不能为空')
    return service.search(q.strip(), market, limit)


@router.get('/groups')
def list_groups(service: Service):
    return service.repository.list_groups()


@router.post('/groups', status_code=201)
def create_group(body: CreateGroup, service: Service):
    return service.repository.create_group(body.name, body.market)


@router.put('/groups/order')
def reorder_groups(body: Order, service: Service):
    service.repository.reorder(body.ids)
    return {'status': 'success'}


@router.patch('/groups/{group_id}')
def rename_group(group_id: int, body: GroupName, service: Service):
    return service.repository.rename_group(group_id, body.name)


@router.delete('/groups/{group_id}')
def delete_group(group_id: int, service: Service):
    service.repository.delete_group(group_id)
    return {'status': 'success'}


@router.get('/groups/{group_id}/items')
def list_items(group_id: int, service: Service):
    return service.list_items(group_id)


@router.post('/groups/{group_id}/items', status_code=201)
def add_item(group_id: int, body: AddItem, service: Service):
    return service.add_item(group_id, body.market, body.symbol)


@router.put('/groups/{group_id}/items/order')
def reorder_items(group_id: int, body: Order, service: Service):
    service.repository.reorder(body.ids, group_id)
    return {'status': 'success'}


@router.delete('/groups/{group_id}/items/{item_id}')
def delete_item(group_id: int, item_id: int, service: Service):
    service.repository.delete_item(group_id, item_id)
    return {'status': 'success'}
