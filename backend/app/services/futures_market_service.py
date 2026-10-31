"""从 Tushare 同步主力合约资料，以及自选合约的日线。"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from ..utils.concurrency import concurrent_requests
from ..utils.progress import progress_bar, progress_write

# CFFEX-中金所 DCE-大商所 CZCE-郑商所 SHFE-上期所
# INE-上海国际能源交易中心 GFEX-广州期货交易所
EXCHANGES = ("CFFEX", "DCE", "CZCE", "SHFE", "INE", "GFEX")


class FuturesMarketService:
    def __init__(self, provider, repository, watchlist_repository):
        self.provider = provider
        self.repository = repository
        self.watchlist_repository = watchlist_repository

    def update_contracts(self):
        day = self._latest_trade_date()
        mapping = self._fetch_main_mapping(day)
        frames = {}

        def fetch_exchange(exchange):
            return self._fetch_exchange_contracts(exchange, mapping)

        with concurrent_requests(
            EXCHANGES,
            fetch_exchange,
            max_workers=len(EXCHANGES),
            thread_name_prefix="futures-contracts",
        ) as results:
            with progress_bar(
                results,
                total=len(EXCHANGES),
                desc="同步期货主力合约资料",
                unit="交易所",
                workers=len(EXCHANGES),
            ) as progress:
                for exchange, future in progress:
                    frames[exchange] = future.result()
        # 按交易所原顺序汇总；全部成功后才在调用线程写库。
        contracts = pd.concat(
            [frames[exchange] for exchange in EXCHANGES], ignore_index=True
        )
        if contracts.empty:
            raise RuntimeError("暂无能映射到主力月份的合约，保留原有资料")
        written = self.repository.upsert_contracts(contracts, replace=True)
        self.watchlist_repository.retain_futures_items(
            self.repository.list_contract_symbols()
        )
        progress.finish(written=written)
        return written

    def _latest_trade_date(self):
        # 先从最近一个月的期货日历确定最近交易日，再只查询该日的主力映射。
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        start = (pd.Timestamp(today) - pd.DateOffset(months=1)).date()
        trade_dates = self.provider.fetch_futures_trade_dates(start, today)
        if not trade_dates:
            raise RuntimeError("最近一个月暂无期货交易日，请检查 Tushare 数据及权限")
        return max(trade_dates)

    def _fetch_main_mapping(self, day):
        progress_write(f"查询期货主力映射：{day}")
        mapping = self.provider.fetch_futures_mapping(day)
        if mapping is None or mapping.empty:
            raise RuntimeError(f"{day} 暂无主力合约映射，请检查 Tushare 数据及权限")
        if len(mapping) >= 2000:
            raise RuntimeError("主力合约映射达到接口上限，拒绝保存可能截断的数据")
        mapping = mapping.copy()
        mapping["trade_date"] = pd.to_datetime(
            mapping.trade_date, format="%Y%m%d", errors="raise"
        ).dt.date
        if not mapping.trade_date.eq(day).all():
            raise ValueError("主力合约映射日期与请求日期不一致")
        return mapping.rename(columns={"mapping_ts_code": "main_symbol"})

    def _fetch_exchange_contracts(self, exchange, mapping):
        rows = self.provider.fetch_futures_contracts(exchange)
        if rows is None or rows.empty:
            raise RuntimeError(f"{exchange} 未返回合约资料，请检查 Tushare 权限")
        # fut_type=2 也含连续合约；主力代码的前缀就是品种代码（例如 RB.SHF）。
        rows = rows[
            rows.ts_code.str.split(".").str[0].str.upper() == rows.code.str.upper()
        ]
        rows = rows.merge(
            mapping[["ts_code", "main_symbol", "trade_date"]],
            on="ts_code",
            how="inner",
            validate="one_to_one",
        )
        rows = rows.dropna(subset=["main_symbol"])
        rows = rows[rows.main_symbol.str.strip().ne("")]
        rows = self._attach_main_names(exchange, rows)
        return rows.rename(columns={"ts_code": "symbol"})

    def _attach_main_names(self, exchange, rows):
        if not rows.main_symbol.notna().any():
            rows["main_name"] = None
            return rows
        months = self.provider.fetch_futures_contracts(exchange, fut_type="1")
        if months is None or months.empty or len(months) >= 10000:
            raise RuntimeError(f"{exchange} 月合约资料为空或达到接口上限")
        rows = rows.merge(
            months[["ts_code", "name"]].rename(
                columns={"ts_code": "main_symbol", "name": "main_name"}
            ),
            on="main_symbol",
            how="left",
            validate="many_to_one",
        )
        if rows.loc[rows.main_symbol.notna(), "main_name"].isna().any():
            raise RuntimeError(f"{exchange} 主力对应的月合约资料缺失")
        return rows

    def update_daily_bars(self, lookback_days=365):
        if lookback_days <= 0:
            raise ValueError("lookback_days 必须大于 0")
        pool = self.watchlist_repository.get_pool("FUTURES")
        items = self.watchlist_repository.list_items(pool["id"])
        if not items:
            progress_write("期货合约池为空，跳过日 K 同步")
            return {"contracts": 0, "rows": 0}
        end = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        start = end - timedelta(days=lookback_days - 1)
        # 每次最多一年，单合约不会触及 fut_daily 的 2000 条上限。
        offsets = range(0, lookback_days, 365)
        tasks = (
            (
                item["symbol"],
                start + timedelta(days=offset),
                min(start + timedelta(days=offset + 364), end),
            )
            for item in items
            for offset in offsets
        )
        written = 0
        empty = 0
        failed_batches = []
        task_count = len(items) * len(offsets)
        worker_count = min(10, task_count)

        def fetch_batch(task):
            return self.provider.fetch_futures_daily(*task)

        with concurrent_requests(
            tasks,
            fetch_batch,
            max_workers=worker_count,
            thread_name_prefix="futures-daily-bar",
        ) as results:
            with progress_bar(
                results,
                total=task_count,
                desc="同步期货日 K",
                unit="批",
                range_text=f"{start} 至 {end}",
                workers=worker_count,
            ) as progress:
                for task, future in progress:
                    symbol, chunk_start, chunk_end = task
                    try:
                        rows = future.result()
                        if rows is None or rows.empty:
                            empty += 1
                            continue
                        rows = rows.rename(
                            columns={
                                "ts_code": "symbol",
                                "vol": "volume",
                                "oi": "open_interest",
                            }
                        ).copy()
                        rows["trade_date"] = pd.to_datetime(
                            rows.trade_date, format="%Y%m%d"
                        ).dt.date
                        rows["amount"] = (
                            rows.amount * 10000
                        )  # Tushare 成交额：万元 → 元。
                        # 请求在线程池完成，整理和写库由调用线程串行执行。
                        written += self.repository.upsert_daily_bars(rows)
                    except Exception as error:
                        batch = f"{symbol} ({chunk_start} 至 {chunk_end})"
                        failed_batches.append(batch)
                        progress_write(f"{batch} 日 K 同步失败：{error}")
        progress.finish(written=written, empty=empty, failed=len(failed_batches))
        if failed_batches:
            raise RuntimeError(
                f"期货日 K 未完整同步，已写入 {written} 条，失败批次："
                + ", ".join(sorted(failed_batches))
            )
        return {"contracts": len(items), "rows": written}
