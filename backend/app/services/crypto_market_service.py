"""从币安同步日 K，并转换为本地行情表字段。"""

from datetime import datetime, timedelta, timezone

import pandas as pd

from ..provider import BinanceProvider
from ..repository.crypto_market_db import CryptoMarketRepository
from ..repository.watchlist import WatchlistRepository
from ..utils.concurrency import concurrent_requests
from ..utils.progress import progress_bar, progress_write


class CryptoMarketService:
    def __init__(
        self,
        provider: BinanceProvider,
        repository: CryptoMarketRepository,
        *,
        watchlist_repository: WatchlistRepository | None = None,
    ):
        self.provider = provider
        self.repository = repository
        self.watchlist_repository = watchlist_repository

    @staticmethod
    def _daily_range(days: int) -> tuple[datetime, datetime]:
        if days <= 0:
            raise ValueError("lookback_days 必须大于 0")
        now = datetime.now(timezone.utc)
        # 从 UTC 零点开始，防止漏掉起始日；包含当天尚未收盘的 K 线。
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        return start, now

    def _fetch_daily_bars(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        rows = self.provider.fetch_historical(
            symbol, int(start.timestamp() * 1000), int(end.timestamp() * 1000)
        )
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame(rows).rename(columns={
            "open_price": "open", "high_price": "high",
            "low_price": "low", "close_price": "close", "turnover": "amount",
        })
        frame["symbol"] = symbol
        frame["trade_date"] = pd.to_datetime(frame.pop("date_ms"), unit="ms", utc=True).dt.date
        return frame

    def sync_daily_bars(self, symbol: str, days: int = 365) -> int:
        start, end = self._daily_range(days)
        return self.repository.upsert_daily_bars(self._fetch_daily_bars(symbol, start, end))

    def sync_group_daily_bars(
        self, symbols: list[str], lookback_days: int = 365
    ) -> dict[str, int]:
        """同步指定分组成员，统一返回资产数和写入行数。"""
        result = self.update_daily_bars(lookback_days=lookback_days, symbols=symbols)
        return {"symbols": len(symbols), "rows": result["rows"]}

    def update_daily_bars(
        self,
        lookback_days: int = 3,
        max_workers: int = 4,
        request_interval: float = 0.5,
        *,
        symbols: list[str] | None = None,
    ) -> dict[str, int]:
        """同步 SQLite CRYPTO 默认池；部分失败时保留成功数据并在结束后抛异常。"""
        start, end = self._daily_range(lookback_days)
        if max_workers <= 0:
            raise ValueError("max_workers 必须大于 0")
        if request_interval < 0:
            raise ValueError("request_interval 不能小于 0")
        if symbols is None:
            if self.watchlist_repository is None:
                raise RuntimeError("未配置交易对池 Repository")
            pool = self.watchlist_repository.get_pool("CRYPTO")
            symbols = [
                row["symbol"] for row in self.watchlist_repository.list_items(pool["id"])
            ]
        if not symbols:
            print("加密货币交易对池为空，跳过日 K 同步")
            return {"symbols": 0, "rows": 0}

        failed_symbols: list[str] = []
        affected_rows = 0
        with concurrent_requests(
            symbols,
            lambda symbol: self._fetch_daily_bars(symbol, start, end),
            max_workers=max_workers,
            request_interval=request_interval,
            thread_name_prefix="crypto-daily-bar",
        ) as results:
            progress = progress_bar(
                results,
                total=len(symbols),
                desc="同步加密货币日 K",
                unit="个交易对",
                range_text=f"{start.date()} 至 {end.date()}（UTC）",
                workers=max_workers,
            )
            for symbol, future in progress:
                try:
                    affected_rows += self.repository.upsert_daily_bars(future.result())
                except Exception as error:
                    failed_symbols.append(symbol)
                    progress_write(f"加密货币 {symbol} 日 K 同步失败：{error}")

        progress.finish(written=affected_rows, failed=len(failed_symbols))
        if failed_symbols:
            raise RuntimeError(
                f"加密货币日 K 未完整同步，已写入 {affected_rows} 条，失败交易对："
                + ", ".join(sorted(failed_symbols))
            )
        return {"symbols": len(symbols), "rows": affected_rows}
