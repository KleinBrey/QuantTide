from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
