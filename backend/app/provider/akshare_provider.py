"""使用 AkShare 获取 A 股基础信息和历史行情。

文件名特意使用 akshare_provider.py，避免直接运行时遮蔽 akshare 第三方包。
"""

from __future__ import annotations

import os

import akshare as ak
import pandas as pd
import requests

from ..utils.symbol import exchange_for, validate_symbol


class AkShareProvider:
    """把 AkShare 返回的数据适配为 app 服务使用的结构。"""

    source = "AkShare"

    # AkShare 的 A 股列表会分别请求沪、深、北交所；历史行情会请求
    # 东方财富，并可能回退到腾讯。本地代理不可用时，这些数据源应直连。
    _NO_PROXY_DOMAINS = (
        ".sse.com.cn",
        ".szse.cn",
        ".bse.cn",
        ".eastmoney.com",
        ".qq.com",
    )

    _INTERVAL_MAP = {
        "1d": "daily",
        "daily": "daily",
        "1w": "weekly",
        "weekly": "weekly",
        "1mo": "monthly",
        "monthly": "monthly",
    }
    _ADJUST_MAP = {
        "": "",
        "none": "",
        "raw": "",
        "forward": "qfq",
        "qfq": "qfq",
        "backward": "hfq",
        "hfq": "hfq",
    }

    def __init__(
        self,
        *,
        timeout: float | None = 30,
        bypass_data_source_proxy: bool = True,
    ):
        self.timeout = timeout
        if bypass_data_source_proxy:
            for domain in self._NO_PROXY_DOMAINS:
                self._add_no_proxy_domain(domain)

    @staticmethod
    def _add_no_proxy_domain(domain: str) -> None:
        """将数据源域名加入 requests 识别的代理豁免列表。"""

        for variable_name in ("NO_PROXY", "no_proxy"):
            current_value = os.environ.get(variable_name, "")
            domains = [
                item.strip() for item in current_value.split(",") if item.strip()
            ]
            if domain not in domains:
                domains.append(domain)
            os.environ[variable_name] = ",".join(domains)

    @staticmethod
    def _timestamp_to_date(timestamp_ms: int) -> str:
        """把毫秒时间戳转换为上海时区的 YYYYMMDD 日期。"""

        timestamp = pd.to_datetime(timestamp_ms, unit="ms", utc=True)
        return timestamp.tz_convert("Asia/Shanghai").strftime("%Y%m%d")

    def fetch_stock_list(self) -> dict:
        """获取沪、深、北交易所的全部 A 股。"""

        frame = ak.stock_info_a_code_name()

        items = []
        for row in frame.itertuples(index=False):
            code = validate_symbol(row.code)
            items.append(
                {
                    "ticker": code,
                    "name": row.name,
                    "exchange": exchange_for(code),
                    "source": self.source,
                }
            )

        return {"data": {"item": items}}

    def fetch_historical(
        self,
        thscode: str,
        start: int,
        end: int,
        interval: str = "1d",
        adjust: str = "forward",
        offset: int = 0,
    ) -> dict:
        """获取股票历史行情，并返回 CNMarketService 能处理的字段。"""

        code = validate_symbol(thscode)

        try:
            period = self._INTERVAL_MAP[interval.lower()]
        except KeyError as error:
            raise ValueError(f"AkShare 不支持行情周期: {interval!r}") from error

        try:
            adjustment = self._ADJUST_MAP[adjust.lower()]
        except KeyError as error:
            raise ValueError(f"AkShare 不支持复权方式: {adjust!r}") from error

        if offset < 0:
            raise ValueError("offset 不能小于 0")

        start_date = self._timestamp_to_date(start)
        end_date = self._timestamp_to_date(end)

        try:
            frame = ak.stock_zh_a_hist(
                symbol=code,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust=adjustment,
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException:
            if period != "daily":
                raise

            # 东方财富接口偶尔会断开代理或直连请求，日线数据回退到腾讯接口。
            exchange = exchange_for(code).lower()
            frame = ak.stock_zh_a_hist_tx(
                symbol=f"{exchange}{code}",
                start_date=start_date,
                end_date=end_date,
                adjust=adjustment,
                timeout=self.timeout,
            )
            frame = frame.rename(
                columns={
                    "date": "日期",
                    "open": "开盘",
                    "high": "最高",
                    "low": "最低",
                    "close": "收盘",
                    "volume": "成交量",
                    "amount": "成交额",
                }
            )

        if frame.empty:
            return {"data": {"item": []}}

        column_map = {
            "日期": "date",
            "开盘": "open_price",
            "最高": "high_price",
            "最低": "low_price",
            "收盘": "close_price",
            "成交量": "volume",
            "成交额": "turnover",
        }
        missing_columns = set(column_map).difference(frame.columns)
        if missing_columns:
            missing_text = ", ".join(sorted(missing_columns))
            raise ValueError(f"AkShare 日线数据缺少字段: {missing_text}")

        result = frame[list(column_map)].rename(columns=column_map).copy()
        result = result.iloc[offset:].reset_index(drop=True)

        trade_dates = pd.to_datetime(result.pop("date"), errors="raise")
        shanghai_dates = trade_dates.dt.tz_localize("Asia/Shanghai")
        # Pandas 不同版本的 datetime 内部精度可能是秒、毫秒、微秒或纳秒，
        # 直接 astype("int64") 后再固定除数会得到错误年份。显式转时间戳更稳定。
        result["date_ms"] = shanghai_dates.map(
            lambda value: int(value.timestamp() * 1000)
        )

        numeric_columns = [
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "turnover",
        ]
        for column in numeric_columns:
            result[column] = pd.to_numeric(result[column], errors="raise")

        result["source"] = self.source
        return {"data": {"item": result.to_dict(orient="records")}}
