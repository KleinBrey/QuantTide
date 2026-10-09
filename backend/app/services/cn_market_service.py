"""A 股市场数据格式化与同步服务。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from ..provider import HithinkProvider, IwencaiProvider, TushareProvider
from ..repository import (
    DailyBarRepository,
    DailyBasicRepository,
    DailyHotRepository,
    DailyStockRepository,
)
from ..utils.concurrency import concurrent_requests
from ..utils.progress import progress_bar, progress_write
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

    def update_daily_stocks(self, lookback_days: int | None = None) -> int:
        """同步最新股票池，或覆盖最近 N 个自然日内的交易日快照。"""

        # 1. 确定同步日期；None 交给数据源处理，表示最新交易日。
        if lookback_days is not None and lookback_days <= 0:
            raise ValueError("lookback_days 必须大于 0")

        if lookback_days is None:
            trade_dates = [None]
            range_text = "最新交易日"
        else:
            end_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            start_date = end_date - timedelta(days=lookback_days - 1)
            if start_date < date(2016, 1, 1):
                raise ValueError("历史股票池范围必须从 2016-01-01 起")
            trade_dates = self.tushare_provider.fetch_trade_dates(start_date, end_date)
            range_text = f"{start_date} 至 {end_date}"

        if not trade_dates:
            print(f"{range_text} 无交易日，跳过股票池同步")
            return 0

        # 2. 准备并发数量和结果统计。
        max_workers = 10
        worker_count = min(max_workers, len(trade_dates))
        written_rows = 0
        empty_count = 0
        failed_dates = []

        # 3. 并发获取数据，按请求完成顺序在主线程整理、写入。
        with concurrent_requests(
            trade_dates,
            self.tushare_provider.fetch_stock_list,
            max_workers=worker_count,
            request_interval=0.6,
            thread_name_prefix="daily-stocks",
        ) as results:
            progress = progress_bar(
                results,
                total=len(trade_dates),
                desc="覆盖同步股票池",
                unit="交易日",
                range_text=range_text,
                workers=worker_count,
            )
            for trade_date, future in progress:
                date_text = trade_date.isoformat() if trade_date else "最新交易日"
                try:
                    result = future.result()
                    if result is None or result.empty:
                        empty_count += 1
                        progress_write(f"{date_text} 股票池暂无数据，本次跳过")
                        continue

                    stock_list = self.format_stock_list(result, "Tushare")
                    # 数据库写入放在主线程，避免多个线程同时写同一张表。
                    written_rows += self.daily_stock_repository.upsert_stocks(
                        stock_list
                    )
                except Exception as error:
                    failed_dates.append(date_text)
                    progress_write(f"{date_text} 股票池同步失败：{error}")

        # 4. 汇总结果；成功日期已保存，失败日期可以重跑补齐。
        progress.finish(
            written=written_rows, empty=empty_count, failed=len(failed_dates)
        )
        if failed_dates:
            raise RuntimeError(
                f"股票池未完整同步，已写入 {written_rows} 条，失败日期："
                + ", ".join(sorted(failed_dates))
            )
        return written_rows

    def update_daily_basic(self, lookback_days: int | None = None) -> int:
        """同步最新每日指标，或最近 N 个自然日内的交易日指标。"""

        # 1. 确定同步日期；None 交给数据源处理，表示最新交易日。
        if lookback_days is not None and lookback_days <= 0:
            raise ValueError("lookback_days 必须大于 0")

        if lookback_days is None:
            trade_dates = [None]
            range_text = "最新交易日"
        else:
            end_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            start_date = end_date - timedelta(days=lookback_days - 1)
            trade_dates = self.tushare_provider.fetch_trade_dates(start_date, end_date)
            range_text = f"{start_date} 至 {end_date}"

        if not trade_dates:
            print(f"{range_text} 无交易日，跳过每日指标同步")
            return 0

        # 2. 准备并发数量和结果统计。
        max_workers = 10
        worker_count = min(max_workers, len(trade_dates))
        written_rows = 0
        empty_count = 0
        failed_dates = []

        # 3. 并发获取数据，按请求完成顺序在主线程写入。
        with concurrent_requests(
            trade_dates,
            self.tushare_provider.fetch_daily_basic,
            max_workers=worker_count,
            thread_name_prefix="daily-basic",
        ) as results:
            progress = progress_bar(
                results,
                total=len(trade_dates),
                desc="同步股票每日指标",
                unit="交易日",
                range_text=range_text,
                workers=worker_count,
            )
            for trade_date, future in progress:
                date_text = trade_date.isoformat() if trade_date else "最新交易日"
                try:
                    # 数据源已完成指标格式化，这里直接取结果。
                    daily_basic = future.result()
                    if daily_basic is None or daily_basic.empty:
                        empty_count += 1
                        progress_write(f"{date_text} 每日指标暂无数据，本次跳过")
                        continue

                    # 数据库写入放在主线程，避免多个线程同时写同一张表。
                    written_rows += (
                        self.daily_basic_repository.upsert_stock_daily_basic(
                            daily_basic
                        )
                    )
                except Exception as error:
                    failed_dates.append(date_text)
                    progress_write(f"{date_text} 每日指标同步失败：{error}")

        # 4. 汇总结果；成功日期已保存，失败日期可以重跑补齐。
        progress.finish(
            written=written_rows, empty=empty_count, failed=len(failed_dates)
        )
        if failed_dates:
            raise RuntimeError(
                f"每日指标未完整同步，已写入 {written_rows} 条，失败日期："
                + ", ".join(sorted(failed_dates))
            )
        return written_rows

    def update_daily_bars(self, lookback_days: int = 60) -> int:
        """同步最近 N 个自然日（含今天）内的全市场日 K。"""

        # 1. 确定同步日期，只请求交易日的数据。
        if lookback_days <= 0:
            raise ValueError("lookback_days 必须大于 0")

        end_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        start_date = end_date - timedelta(days=lookback_days - 1)
        trade_dates = self.tushare_provider.fetch_trade_dates(start_date, end_date)
        range_text = f"{start_date} 至 {end_date}"

        if not trade_dates:
            print(f"{range_text} 无交易日，跳过日 K 同步")
            return 0

        # 2. 准备并发数量和结果统计。
        max_workers = 10
        worker_count = min(max_workers, len(trade_dates))
        written_rows = 0
        empty_count = 0
        failed_dates = []

        # 3. 并发获取数据，按请求完成顺序在主线程整理、写入。
        with concurrent_requests(
            trade_dates,
            self.tushare_provider.fetch_daily_bar,
            max_workers=worker_count,
            thread_name_prefix="daily-bar",
        ) as results:
            progress = progress_bar(
                results,
                total=len(trade_dates),
                desc="同步股票日线",
                unit="交易日",
                range_text=range_text,
                workers=worker_count,
            )
            for trade_date, future in progress:
                date_text = trade_date.isoformat() if trade_date else "最新交易日"
                try:
                    result = future.result()
                    if result is None or result.empty:
                        empty_count += 1
                        progress_write(f"{date_text} 日 K 暂无数据，本次跳过")
                        continue

                    daily_list = self.format_daily_list(result)

                    if daily_list.empty:
                        empty_count += 1
                        continue

                    # 跳过零成交量记录。
                    zero_volume = daily_list["volume"].eq(0)
                    if zero_volume.any():
                        progress_write(
                            f"{date_text} 日 K 跳过 {zero_volume.sum()} 条零成交量记录"
                        )
                        daily_list = daily_list.loc[~zero_volume]

                    # 数据库写入放在主线程，避免多个线程同时写同一张表。
                    written_rows += self.daily_repository.upsert_daily_bars(daily_list)
                except Exception as error:
                    failed_dates.append(date_text)
                    progress_write(f"{date_text} 日 K 同步失败：{error}")

        # 4. 汇总结果；成功日期已保存，失败日期可以重跑补齐。
        progress.finish(
            written=written_rows, empty=empty_count, failed=len(failed_dates)
        )
        if failed_dates:
            raise RuntimeError(
                f"日 K 未完整同步，已写入 {written_rows} 条，失败日期："
                + ", ".join(sorted(failed_dates))
            )
        return written_rows
