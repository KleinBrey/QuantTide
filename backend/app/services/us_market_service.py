"""美股市场数据服务。"""

import time
from typing import Any

import pandas as pd

from ..provider import IwencaiProvider, YFinanceProvider
from ..repository import USDailyBarRepository, USStockHotDailyRepository
from ..repository.watchlist import WatchlistRepository
from ..utils.concurrency import concurrent_requests
from ..utils.progress import progress_bar, progress_write
from .hot_stock_service import HotStockService


class USMarketService(HotStockService):
    """负责美股日 K 同步、热度数据同步与缓存。"""

    def __init__(
        self,
        iwencai_provider: IwencaiProvider | None = None,
        stock_hot_repository: USStockHotDailyRepository | None = None,
        *,
        yfinance_provider: YFinanceProvider | None = None,
        daily_repository: USDailyBarRepository | None = None,
        watchlist_repository: WatchlistRepository | None = None,
    ) -> None:
        super().__init__(
            iwencai_provider=iwencai_provider,
            stock_hot_repository=stock_hot_repository,
            fetch_method_name="fetch_us_hot_rank",
            market_name="美股",
        )
        self.yfinance_provider = yfinance_provider
        self.daily_repository = daily_repository
        self.watchlist_repository = watchlist_repository

    @staticmethod
    def format_daily_list(
        symbol: str,
        result: dict[str, dict[str, list[dict[str, Any]]]],
    ) -> pd.DataFrame:
        """将 Yahoo Finance 历史行情转换为 ``daily_bars`` 表结构。"""

        columns = [
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "source",
        ]
        items = result.get("data", {}).get("item", [])
        frame = pd.DataFrame(items)
        if frame.empty:
            return pd.DataFrame(columns=columns)

        required_columns = [
            "date_ms",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
        ]
        missing_columns = [
            column for column in required_columns if column not in frame.columns
        ]
        if missing_columns:
            raise ValueError(
                f"Yahoo Finance 日 K 数据缺少字段：{', '.join(missing_columns)}"
            )

        frame["symbol"] = str(symbol).strip().upper()
        frame["trade_date"] = (
            pd.to_datetime(frame["date_ms"], unit="ms", utc=True)
            .dt.tz_convert("Asia/Shanghai")
            .dt.date
        )
        frame["open"] = pd.to_numeric(frame["open_price"], errors="raise")
        frame["high"] = pd.to_numeric(frame["high_price"], errors="raise")
        frame["low"] = pd.to_numeric(frame["low_price"], errors="raise")
        frame["close"] = pd.to_numeric(frame["close_price"], errors="raise")
        frame["volume"] = pd.to_numeric(frame["volume"], errors="raise")
        # Yahoo 日线没有真实成交额，不以收盘价乘成交量替代。
        frame["amount"] = None
        if "source" not in frame.columns:
            frame["source"] = YFinanceProvider.source
        else:
            frame["source"] = frame["source"].fillna(YFinanceProvider.source)

        return frame[columns].reset_index(drop=True)

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
        now_ms: int | None = None,
        symbols: list[str] | None = None,
    ) -> dict[str, int]:
        """同步 SQLite US 股票池日 K；部分失败时保留成功数据并在结束后抛异常。"""
        if lookback_days <= 0:
            raise ValueError("lookback_days 必须大于 0")
        if max_workers <= 0:
            raise ValueError("max_workers 必须大于 0")
        if request_interval < 0:
            raise ValueError("request_interval 不能小于 0")

        if (
            self.yfinance_provider is None
            or self.daily_repository is None
            or (symbols is None and self.watchlist_repository is None)
        ):
            raise RuntimeError("未配置 YFinance Provider、日 K 或股票池 Repository")

        if symbols is None:
            pool = self.watchlist_repository.get_pool("US")
            symbols = [
                row["symbol"] for row in self.watchlist_repository.list_items(pool["id"])
            ]
        if not symbols:
            print(f"{self._market_name}股票池为空，跳过日 K 同步")
            return {"stocks": 0, "rows": 0}

        end = now_ms if now_ms is not None else int(time.time() * 1000)
        start = end - lookback_days * 24 * 60 * 60 * 1000

        def fetch_symbol(symbol: str):
            return self.yfinance_provider.fetch_historical(
                symbol,
                start,
                end,
                interval="1d",
                adjust="forward",
            )

        failed_symbols: list[str] = []
        affected_rows = 0

        with concurrent_requests(
            symbols,
            fetch_symbol,
            max_workers=max_workers,
            request_interval=request_interval,
            thread_name_prefix=f"{self._market_name}-daily-bar",
        ) as results:
            progress = progress_bar(
                results,
                total=len(symbols),
                desc=f"同步{self._market_name}日 K",
                unit="只",
                range_text=f"{pd.Timestamp(start, unit='ms', tz='Asia/Shanghai').date()} 至 "
                f"{pd.Timestamp(end, unit='ms', tz='Asia/Shanghai').date()}",
                workers=max_workers,
            )
            for symbol, future in progress:
                try:
                    rows = self.format_daily_list(symbol, future.result())
                    # 与 A 股同步保持一致，不保存没有成交量的行情。
                    rows = rows[rows["volume"].notna() & rows["volume"].ne(0)]
                    if rows.empty:
                        continue
                    affected_rows += self.daily_repository.upsert_daily_bars(rows)
                except Exception as error:
                    failed_symbols.append(symbol)
                    progress_write(f"{self._market_name} {symbol} 日 K 同步失败：{error}")

        progress.finish(written=affected_rows, failed=len(failed_symbols))
        if failed_symbols:
            raise RuntimeError(
                f"{self._market_name}日 K 未完整同步，已写入 {affected_rows} 条，失败股票："
                + ", ".join(sorted(failed_symbols))
            )
        return {
            "stocks": len(symbols),
            "rows": affected_rows,
        }
