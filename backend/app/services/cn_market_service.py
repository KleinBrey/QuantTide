"""A 股市场数据格式化与同步服务。"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from ..provider import HithinkProvider, IwencaiProvider, TushareProvider
from ..repository import (
    DailyBarRepository,
    DailyHotRepository,
    DailyBasicRepository,
    DailyStockRepository,
)
from ..utils.progress import progress_bar, progress_write
from ..utils.concurrency import concurrent_requests
from .hot_stock_service import HotStockService


class CNMarketService(HotStockService):
    """负责 A 股股票列表、行情、指标与热度数据。"""

    def __init__(
        self,
        hithink_provider: HithinkProvider | None = None,
        tushare_provider: TushareProvider | None = None,
        daily_stock_repository: DailyStockRepository | None = None,
        daily_basic_repository: DailyBasicRepository | None = None,
        daily_repository: DailyBarRepository | None = None,
        iwencai_provider: IwencaiProvider | None = None,
        daily_hot_repository: DailyHotRepository | None = None,
    ) -> None:
        super().__init__(
            iwencai_provider=iwencai_provider,
            stock_hot_repository=daily_hot_repository,
            fetch_method_name="fetch_hot_rank",
            market_name="A 股",
        )
        self.hithink_provider = hithink_provider
        self.tushare_provider = tushare_provider
        self.daily_stock_repository = daily_stock_repository
        self.daily_basic_repository = daily_basic_repository
        self.daily_repository = daily_repository

    @staticmethod
    def format_stock_list(value: pd.DataFrame, source: str) -> pd.DataFrame:
        """格式化股票列表数据"""

        frame = pd.DataFrame(value)
        columns = ["symbol", "trade_date", "name", "exchange", "market", "source"]
        # 交易所
        exchange_map = {
            "SSE": "SH",
            "SZSE": "SZ",
            "BSE": "BJ",
        }
        # 如果 DataFrame 为空，返回只有列定义的空 DataFrame
        if frame.empty:
            return pd.DataFrame(columns=columns)
        # 格式转换
        frame["symbol"] = frame["ts_code"]
        frame["exchange"] = frame["exchange"].replace(exchange_map)
        frame["source"] = source
        # 只保留目标列，并按 columns 中的顺序排列
        return frame[columns].reset_index(drop=True)

    @staticmethod
    def format_hithink_daily_list(symbol: str, value: list) -> pd.DataFrame:
        """格式化同花顺日线股票列表数据"""

        frame = pd.DataFrame(value)
        columns = [
            "symbol",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "source",
        ]
        # 如果 DataFrame 为空，返回只有列定义的空 DataFrame
        if frame.empty:
            return pd.DataFrame(columns=columns)
        # 格式转换
        frame["symbol"] = symbol
        frame["date"] = (
            pd.to_datetime(frame["date_ms"], unit="ms", utc=True)
            .dt.tz_convert("Asia/Shanghai")
            .dt.date
        )
        frame["open"] = frame["open_price"].round(2)
        frame["high"] = frame["high_price"].round(2)
        frame["low"] = frame["low_price"].round(2)
        frame["close"] = frame["close_price"].round(2)
        frame["volume"] = frame["volume"]
        frame["amount"] = frame["turnover"]
        if "source" not in frame.columns:
            frame["source"] = "Hithink"
        else:
            frame["source"] = frame["source"].fillna("Hithink")

        # 只保留目标列，并按 columns 中的顺序排列
        return frame[columns].reset_index(drop=True)

    @staticmethod
    def format_daily_list(value: list) -> pd.DataFrame:
        """格式化日线股票列表数据"""

        frame = pd.DataFrame(value)
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
        # 如果 DataFrame 为空，返回只有列定义的空 DataFrame
        if frame.empty:
            return pd.DataFrame(columns=columns)
        # 格式转换
        frame["symbol"] = frame["ts_code"]
        frame["trade_date"] = frame["trade_date"]
        frame["open"] = frame["open"]
        frame["high"] = frame["high"]
        frame["low"] = frame["low"]
        frame["close"] = frame["close"]
        frame["volume"] = frame["vol"]
        frame["amount"] = frame["amount"]
        frame["source"] = "Tushare"

        # 只保留目标列，并按 columns 中的顺序排列
        return frame[columns].reset_index(drop=True)

    def update_daily_stocks(
        self,
        lookback_days: int | None = None,
    ) -> int:
        """同步最新股票池，或按交易日覆盖最近 N 个自然日（含今天）的快照。"""

        # 默认开10个线程
        max_workers: int = 10

        if lookback_days is None:
            days: list[date | None] = [None]
            range_text = "最新交易日"
        else:
            if lookback_days <= 0:
                raise ValueError("lookback_days 必须大于 0")
            end = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            start = end - timedelta(days=lookback_days - 1)
            if start < date(2016, 1, 1):
                raise ValueError("历史股票池范围必须从 2016-01-01 起")
            days = self.tushare_provider.fetch_trade_dates(start, end)
            if not days:
                print(f"{start} 至 {end} 无交易日，跳过股票池同步")
                return 0
            range_text = f"{start} 至 {end}"

        worker_count = min(max_workers, len(days))

        def fetch(day: date | None) -> pd.DataFrame:
            # API 请求数据
            result = self.tushare_provider.fetch_stock_list(day)
            # 格式化清洗数据
            stock_list = self.format_stock_list(result, "Tushare")
            return stock_list

        total, failures = 0, []
        with concurrent_requests(
            days,
            fetch,
            max_workers=max_workers,
            request_interval=0.6,
            thread_name_prefix="daily-stocks",
        ) as results:
            progress = progress_bar(
                results,
                total=len(days),
                desc="覆盖同步股票池",
                unit="交易日",
                range_text=range_text,
                workers=worker_count,
            )
            for day, future in progress:
                try:
                    total += self.daily_stock_repository.upsert_stocks(future.result())
                except Exception as error:
                    day_text = day.isoformat() if day else "最新交易日"
                    failures.append(day_text)
                    progress_write(f"{day_text} 同步失败：{error}")
        progress.finish(written=total, failed=len(failures))
        if failures:
            raise RuntimeError(
                "股票池未完整同步，可重跑覆盖同步：" + ", ".join(sorted(failures))
            )
        return total

    def update_daily_basic(
        self,
        lookback_days: int | None = None,
    ) -> int:
        """按交易日并发获取股票每日指标，并在主线程中依次写入数据库。"""

        # 默认开10个线程
        max_workers: int = 10

        if lookback_days is None:
            dates: list[date | None] = [None]
        else:
            if lookback_days <= 0:
                raise ValueError("lookback_days 必须大于 0")

            end_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            start_date = end_date - timedelta(days=lookback_days - 1)
            dates = self.tushare_provider.fetch_trade_dates(start_date, end_date)
            if not dates:
                print(f"{start_date} 至 {end_date} 无交易日，跳过每日指标同步")
                return 0
        affected_rows = 0
        failed_dates: list[date | None] = []

        # 每个交易日为一个请求任务，结果由主线程写入。
        worker_count = min(max_workers, len(dates))
        with concurrent_requests(
            dates,
            self.tushare_provider.fetch_daily_basic,
            max_workers=max_workers,
            thread_name_prefix="daily-basic",
        ) as results:
            progress = progress_bar(
                results,
                total=len(dates),
                desc="同步股票每日指标",
                unit="交易日",
                range_text=(
                    "最新交易日"
                    if lookback_days is None
                    else f"{start_date} 至 {end_date}"
                ),
                workers=worker_count,
            )
            for trade_date, future in progress:
                try:
                    daily_basic = future.result()
                except Exception as error:
                    failed_dates.append(trade_date)
                    date_text = trade_date.isoformat() if trade_date else "最新交易日"
                    progress_write(f"{date_text} 每日指标获取失败: {error}")
                    continue

                # DuckDB 写入集中在主线程，避免多个连接并发写同一张表。
                affected_rows += self.daily_basic_repository.upsert_stock_daily_basic(
                    daily_basic
                )

        progress.finish(written=affected_rows, failed=len(failed_dates))
        return affected_rows

    def update_daily_bars(self, lookback_days: int = 60) -> int:
        """按交易日获取最近 N 个自然日（含今天）的全市场日 K。"""
        if lookback_days <= 0:
            raise ValueError("lookback_days 必须大于 0")

        end_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        start_date = end_date - timedelta(days=lookback_days - 1)
        dates = self.tushare_provider.fetch_trade_dates(start_date, end_date)
        if not dates:
            print(f"{start_date} 至 {end_date} 无交易日，跳过日 K 同步")
            return 0

        affected_rows = 0
        failed_dates: list[date] = []
        worker_count = min(10, len(dates))
        with concurrent_requests(
            dates,
            self.tushare_provider.fetch_daily_bar,
            max_workers=10,
            thread_name_prefix="daily-bar",
        ) as results:
            progress = progress_bar(
                results,
                total=len(dates),
                desc="同步股票日线",
                unit="交易日",
                range_text=f"{start_date} 至 {end_date}",
                workers=worker_count,
            )
            for trade_date, future in progress:
                try:
                    result = future.result()
                    if result is None or result.empty:
                        raise RuntimeError(
                            "交易日日 K 数据为空，可能尚未发布，请稍后重试"
                        )
                    daily_list = self.format_daily_list(result)
                    daily_list = daily_list[
                        daily_list["volume"].notna() & (daily_list["volume"] != 0)
                    ]
                    # DuckDB 写入集中在主线程，避免并发写同一张表。
                    affected_rows += self.daily_repository.upsert_daily_bars(daily_list)
                except Exception as error:
                    failed_dates.append(trade_date)
                    progress_write(f"{trade_date} 日 K 同步失败: {error}")

        progress.finish(written=affected_rows, failed=len(failed_dates))
        if failed_dates:
            raise RuntimeError(
                f"日 K 未完整同步，已写入 {affected_rows} 条，失败日期："
                + ", ".join(map(str, sorted(failed_dates)))
            )
        return affected_rows

    def update_hithink_daily_bar(self):
        """获取同花顺股票历史日K线数据"""

        end = int(time.time() * 1000)

        start = end - 30 * 24 * 60 * 60 * 1000

        stocks_list_from_db = self.daily_stock_repository.get_latest_data()

        symbols = [
            f"{stock.symbol}.{stock.exchange}"
            for stock in stocks_list_from_db.itertuples(index=False)
        ]
        affected_rows, failed = 0, 0
        with concurrent_requests(
            symbols,
            lambda symbol: self.hithink_provider.fetch_historical(symbol, start, end),
            max_workers=10,
            request_interval=0,
            thread_name_prefix="daily-bar",
        ) as results:
            progress = progress_bar(
                results,
                total=len(symbols),
                desc="同步同花顺股票日线",
                unit="只",
                range_text=f"{pd.Timestamp(start, unit='ms', tz='Asia/Shanghai').date()} 至 "
                f"{pd.Timestamp(end, unit='ms', tz='Asia/Shanghai').date()}",
                workers=min(10, len(symbols)),
            )
            for symbol, future in progress:
                try:
                    # API 请求数据
                    result = future.result()
                    # 格式化清洗数据
                    daily_list = self.format_hithink_daily_list(
                        symbol.split(".")[0], result
                    )
                    # 存到数据库
                    affected_rows += self.daily_repository.upsert_daily_bars(daily_list)

                except Exception as e:
                    failed += 1
                    progress_write(f"{symbol} 获取失败: {e}")

        progress.finish(written=affected_rows, failed=failed)
