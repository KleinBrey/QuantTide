"""从币安同步日 K，并转换为本地行情表字段。"""

from datetime import datetime, timedelta, timezone

import pandas as pd

from ..provider import BinanceProvider
from ..repository.crypto_market_db import CryptoMarketRepository


class CryptoMarketService:
    def __init__(self, provider: BinanceProvider, repository: CryptoMarketRepository):
        self.provider = provider
        self.repository = repository

    def sync_daily_bars(self, symbol: str, days: int = 365) -> int:
        now = datetime.now(timezone.utc)
        # 从 UTC 零点开始，防止漏掉起始日；包含当天尚未收盘的 K 线。
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        rows = self.provider.fetch_historical(
            symbol, int(start.timestamp() * 1000), int(now.timestamp() * 1000)
        )
        if not rows:
            return 0
        frame = pd.DataFrame(rows).rename(columns={
            "open_price": "open", "high_price": "high",
            "low_price": "low", "close_price": "close", "turnover": "amount",
        })
        frame["symbol"] = symbol
        frame["trade_date"] = pd.to_datetime(frame.pop("date_ms"), unit="ms", utc=True).dt.date
        return self.repository.upsert_daily_bars(frame)
