"""A 股市场数据格式化与同步服务。"""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from tqdm.auto import tqdm

from ..provider import HithinkProvider, IwencaiProvider, TushareProvider
from ..repository import (
    DailyBarRepository,
    StockHotDailyRepository,
    StockDailyBasicRepository,
    StockRepository,
)
from ..utils.symbol import chunked
from .hot_stock_service import HotStockService


class CNMarketService(HotStockService):
    """负责 A 股股票列表、行情、指标与热度数据。"""

    def __init__(
        self,
        hithink_provider: HithinkProvider | None = None,
        tushare_provider: TushareProvider | None = None,
        stock_repository: StockRepository | None = None,
        stock_daily_basic_repository: StockDailyBasicRepository | None = None,
        daily_repository: DailyBarRepository | None = None,
        iwencai_provider: IwencaiProvider | None = None,
        stock_hot_repository: StockHotDailyRepository | None = None,
    ) -> None:
        super().__init__(
            iwencai_provider=iwencai_provider,
            stock_hot_repository=stock_hot_repository,
            fetch_method_name="fetch_hot_rank",
            market_name="A 股",
        )
        self.hithink_provider = hithink_provider
        self.tushare_provider = tushare_provider
        self.stock_repository = stock_repository
        self.stock_daily_basic_repository = stock_daily_basic_repository
        self.daily_repository = daily_repository

    @staticmethod
    def format_stock_list(value: pd.DataFrame, source: str) -> pd.DataFrame:
        """格式化股票列表数据"""

        frame = pd.DataFrame(value)
        columns = ["symbol", "name", "exchange", "market", "source"]
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
        frame["exchange"] = frame["exchange"].map(exchange_map)
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

    def update_stocks_list(self):
        """获取股票列表数据"""
        try:
            # API 请求数据
            result = self.tushare_provider.fetch_stock_list()
            # 格式化清洗数据
            stock_list = self.format_stock_list(result, "Tushare")
            # 存到数据库
            self.stock_repository.insert_stocks(stock_list)
        except Exception as e:
            print(f"股票列表更新失败: {e}")
            raise
        else:
            print("股票列表更新成功!")

    def update_stock_daily_basic(self) -> int:
        """获取并保存最新交易日的股票每日指标。"""

        daily_basic = self.tushare_provider.fetch_daily_basic()
        affected_rows = self.stock_daily_basic_repository.upsert_stock_daily_basic(
            daily_basic
        )
        print(f"股票每日指标更新成功，共写入 {affected_rows} 条")
        return affected_rows

    def update_daily_bar(
        self,
        lookback_days: int = 60,
        batch_size: int = 50,
    ):
        """获取股票历史日K线数据"""
        # batch_size 请求一次包含50支股票
        # 60 个自然日用于覆盖策略所需的至少 25 个交易日，并为节假日留余量。

        end = int(time.time() * 1000)

        start = end - lookback_days * 24 * 60 * 60 * 1000

        stocks_list_from_db = self.stock_repository.get_table_data()

        symbols = [
            f"{stock.symbol}" for stock in stocks_list_from_db.itertuples(index=False)
        ]

        batches = list(
            chunked(
                symbols,
                batch_size,
            )
        )

        failed_symbols = []

        """ 控制多个线程之间的请求间隔 """
        request_lock = threading.Lock()

        last_request_time = 0.0

        def fetch_batch(batch):
            # 使用外层作用域的变量
            nonlocal last_request_time

            thscode = ",".join(batch)

            with request_lock:
                now = time.monotonic()

                # 每次请求至少间隔 0.5 ~ 1 秒
                interval = random.uniform(0.5, 1.0)

                wait_time = interval - (now - last_request_time)

                if wait_time > 0:
                    time.sleep(wait_time)

                last_request_time = time.monotonic()

            return self.tushare_provider.fetch_historical(
                thscode,
                start,
                end,
            )

        with ThreadPoolExecutor(
            max_workers=10,
            thread_name_prefix="daily-bar",
        ) as executor:

            futures = {}

            # 1. 提交所有任务
            for batch in batches:
                future = executor.submit(
                    fetch_batch,
                    batch,
                )

                futures[future] = batch

            # 2. 哪个任务先完成，就先处理哪个
            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                desc="同步股票日线",
                unit="批",
            ):
                batch = futures[future]

                try:
                    # API 请求数据
                    result = future.result()

                    # 格式化清洗数据
                    daily_list = self.format_daily_list(result)

                    # 过滤掉volumn = 0 的数据
                    daily_list = daily_list[
                        daily_list["volume"].notna() & (daily_list["volume"] != 0)
                    ]

                    # 存到数据库
                    self.daily_repository.upsert_daily_bars(daily_list)

                except Exception as e:
                    # 当前整批股票都记录为失败
                    failed_symbols.extend(batch)

                    tqdm.write(f"当前股票批次获取失败，共 {len(batch)} 只: {e}")

        print("日线股票列表数据更新完成")

        # 最后统一统计失败股票
        if failed_symbols:
            print(f"获取失败股票数量: {len(failed_symbols)}")

            # print("获取失败股票:")
            # for symbol in failed_symbols:
            #     print(symbol)
        else:
            print("全部股票获取成功")

    def update_hithink_daily_bar(self):
        """获取同花顺股票历史日K线数据"""

        end = int(time.time() * 1000)

        start = end - 30 * 24 * 60 * 60 * 1000

        stocks_list_from_db = self.stock_repository.get_table_data()

        with ThreadPoolExecutor(
            max_workers=10,
            thread_name_prefix="daily-bar",
        ) as executor:

            futures = {}

            # 1. 提交所有任务
            for stock in stocks_list_from_db.itertuples(index=False):
                symbol = f"{stock.symbol}.{stock.exchange}"

                future = executor.submit(
                    self.hithink_provider.fetch_historical,
                    symbol,
                    start,
                    end,
                )

                futures[future] = symbol

            # 2. 哪个任务先完成，就先处理哪个
            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                desc="同步同花顺股票日线",
                unit="个",
            ):
                symbol = futures[future]

                try:
                    # API 请求数据
                    result = future.result()
                    # 格式化清洗数据
                    daily_list = self.format_hithink_daily_list(
                        symbol.split(".")[0], result
                    )
                    # 存到数据库
                    self.daily_repository.upsert_daily_bars(daily_list)

                except Exception as e:
                    tqdm.write(f"{symbol} 获取失败: {e}")

        print("日线股票列表数据更新完成")
