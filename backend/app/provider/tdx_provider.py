"""
数据服务 Key 由 SDK 从 tdxaidata/lib/TdxAiData.ini 读取。
导入 Provider 或构造实例时不加载 SDK、不连接行情服务。
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Iterable, Iterator

import numpy as np
import pandas as pd

from ..utils.symbol import exchange_for


class TdxProviderError(RuntimeError):
    """通达信 SDK 请求失败或返回的数据结构异常。"""


class TdxProvider:
    """将通达信行情适配为项目通用的 ``data.item`` 结构。"""

    source = "Tdx"
    _INTERVAL_MAP = {
        "1d": "1d",
        "daily": "1d",
        "1w": "1w",
        "weekly": "1w",
        "1mo": "1mon",
        "monthly": "1mon",
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "60m": "1h",
    }
    _ADJUST_MAP = {
        "": "none",
        "none": "none",
        "raw": "none",
        "forward": "front",
        "qfq": "front",
        "backward": "back",
        "hfq": "back",
    }
    _BAR_FIELDS = {
        "Open": "open_price",
        "High": "high_price",
        "Low": "low_price",
        "Close": "close_price",
        "Volume": "volume",
        "Amount": "turnover",
    }
    _INTRADAY_FIELDS = {
        "Time": "time",
        "Price": "price",
        "Average": "average_price",
        "Volume": "volume",
        "BSFlag": "bs_flag",
        "LeaveQty": "unmatched_volume",
        "InOutFlag": "in_out_flag",
    }
    _NUMERIC_FIELDS = ("price", "average_price", "volume", "unmatched_volume")
    _CODE_PATTERN = re.compile(r"^(?:(SH|SZ|BJ)\.)?(\d{6})(?:\.(SH|SZ|BJ|ZZ|GZ))?$")
    _BAR_LIMIT = 24000

    def __init__(self, *, client: Any | None = None) -> None:
        # 与其他 Provider 的可注入客户端一致，离线测试不依赖动态库和 Key。
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from tdxaidata import tqs
            except (ImportError, OSError) as error:
                raise TdxProviderError(
                    "无法加载 tdxaidata，请执行 uv sync 并检查本机动态库支持"
                ) from error
            self._client = tqs
        return self._client

    @classmethod
    def _stock_code(cls, value: str) -> str:
        normalized = str(value).strip().upper()
        match = cls._CODE_PATTERN.fullmatch(normalized)
        if match is None:
            raise ValueError(f"不支持的通达信证券代码: {value!r}")
        prefix, code, suffix = match.groups()
        if prefix and suffix:
            raise ValueError("证券代码不能同时包含市场前缀和后缀")
        return f"{code}.{prefix or suffix or exchange_for(code)}"

    @classmethod
    def _stock_codes(cls, values: Iterable[str]) -> list[str]:
        if isinstance(values, str):
            values = [values]
        codes = list(dict.fromkeys(cls._stock_code(value) for value in values))
        if not codes:
            raise ValueError("证券代码列表不能为空")
        return codes

    @staticmethod
    def _date(value: str) -> str:
        for pattern in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, pattern).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                continue
        raise ValueError(f"不支持的日期: {value!r}")

    def _request(self, method: str, **kwargs: Any) -> Any:
        try:
            result = getattr(self.client, method)(**kwargs)
        except TdxProviderError:
            raise
        except Exception as error:
            raise TdxProviderError(f"通达信 {method} 请求失败") from error
        # SDK 会把部分后台错误打印后转为 None，不能当作无行情。
        if result is None:
            raise TdxProviderError(
                f"通达信 {method} 未返回数据，请检查 SDK 配置、Key 和积分"
            )
        if isinstance(result, dict) and (
            str(result.get("ErrorId", 0)) != "0" or "error" in result
        ):
            raise TdxProviderError(f"通达信 {method} 返回错误")
        return result

    def fetch_historical(
        self,
        thscode: str,
        start: int,
        end: int,
        interval: str = "1d",
        adjust: str = "forward",
        offset: int = 0,
    ) -> dict:
        """获取历史 K 线；参数和结果字段与其他历史行情 Provider 一致。

        start/end 是毫秒时间戳；日/周/月 K 包含首尾交易日，分钟 K 按时间筛选。
        成交量沿用 SDK 的股/张单位，成交额由万元转为元。不填充缺失行情。
        达到 SDK 单次 24000 条上限时拒绝返回可能截断的数据，需缩短时间范围。
        """
        if start > end:
            raise ValueError("start 不能晚于 end")
        if offset < 0:
            raise ValueError("offset 不能小于 0")
        try:
            period = self._INTERVAL_MAP[interval.lower()]
            dividend_type = self._ADJUST_MAP[adjust.lower()]
        except KeyError as error:
            raise ValueError(
                f"通达信不支持行情周期或复权方式: {interval!r}, {adjust!r}"
            ) from error
        code = self._stock_code(thscode)
        first = pd.to_datetime(start, unit="ms", utc=True).tz_convert("Asia/Shanghai")
        last = pd.to_datetime(end, unit="ms", utc=True).tz_convert("Asia/Shanghai")
        if period in ("1d", "1w", "1mon"):
            first = first.normalize()
            last = (
                last.normalize() + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
            )
        data = self._request(
            "get_market_data",
            field_list=list(self._BAR_FIELDS),
            stock_list=[code],
            period=period,
            start_time=first.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=last.strftime("%Y-%m-%d %H:%M:%S"),
            count=-1,
            dividend_type=dividend_type,
            fill_data=False,
        )
        if not isinstance(data, dict):
            raise TdxProviderError("通达信 K 线返回格式异常")
        if not data:
            return {"data": {"item": []}}
        missing = set(self._BAR_FIELDS).difference(data)
        if missing:
            raise TdxProviderError(f"通达信 K 线缺少字段: {', '.join(sorted(missing))}")
        series = {}
        for field, target in self._BAR_FIELDS.items():
            frame = data[field]
            if not isinstance(frame, pd.DataFrame):
                raise TdxProviderError(f"通达信 {field} 应为 DataFrame")
            # SDK 1.3.1 为日期索引、证券代码列；兼容文档描述的转置布局。
            if code in frame.columns:
                values = frame[code]
            elif code in frame.index:
                values = frame.loc[code]
            elif frame.empty:
                values = pd.Series(dtype=float)
            else:
                raise TdxProviderError(f"通达信 {field} 缺少证券 {code}")
            if len(values) >= self._BAR_LIMIT:
                raise TdxProviderError(
                    "通达信 K 线达到 24000 条上限，请缩短查询时间范围"
                )
            if series and not values.index.equals(next(iter(series.values())).index):
                raise TdxProviderError("通达信 K 线字段的时间索引不一致")
            series[target] = values
        result = pd.DataFrame(series)
        if result.empty:
            return {"data": {"item": []}}
        try:
            dates = pd.DatetimeIndex(
                pd.to_datetime(result.index.astype(str), format="mixed", errors="raise")
            )
            dates = (
                dates.tz_localize("Asia/Shanghai")
                if dates.tz is None
                else dates.tz_convert("Asia/Shanghai")
            )
            if dates.isna().any():
                raise ValueError("K 线时间为空")
            if period in ("1d", "1w", "1mon"):
                dates = dates.normalize()
            for field in self._BAR_FIELDS.values():
                result[field] = pd.to_numeric(result[field], errors="raise")
            if np.isinf(result.to_numpy(dtype=float)).any():
                raise ValueError("K 线存在无穷值")
        except (TypeError, ValueError) as error:
            raise TdxProviderError("通达信 K 线包含无效时间或数值") from error
        result["date_ms"] = [int(value.timestamp() * 1000) for value in dates]
        result = result.loc[(dates >= first) & (dates <= last)].dropna()
        result["turnover"] *= 10000
        result = result.sort_values("date_ms").drop_duplicates("date_ms", keep="last")
        result["source"] = self.source
        return {"data": {"item": result.iloc[offset:].to_dict(orient="records")}}

    def _intraday_result(self, data: Any, code: str) -> dict:
        total = None
        if isinstance(data, pd.DataFrame):
            frame = data.copy()
        elif isinstance(data, dict):
            total = data.get("TotalNum")
            arrays = {
                key: value for key, value in data.items() if isinstance(value, list)
            }
            if len({len(value) for value in arrays.values()}) > 1:
                raise TdxProviderError("通达信分时字段数组长度不一致")
            if data and not arrays and str(total) != "0":
                raise TdxProviderError("通达信分时数据缺少字段数组")
            frame = pd.DataFrame(arrays)
        elif isinstance(data, list) and not data:
            frame = pd.DataFrame()
        else:
            raise TdxProviderError("通达信分时数据返回格式异常")
        frame = frame.rename(columns=self._INTRADAY_FIELDS)
        try:
            for field in self._NUMERIC_FIELDS:
                if field in frame:
                    frame[field] = pd.to_numeric(frame[field], errors="raise")
                    if not np.isfinite(frame[field].to_numpy(dtype=float)).all():
                        raise ValueError(f"{field} 存在空值或无穷值")
        except (TypeError, ValueError) as error:
            raise TdxProviderError("通达信分时数据包含无效数值") from error
        # 不去重或排序：Tick 可能在同一秒内有多笔成交。
        frame["ticker"] = code
        frame["source"] = self.source
        result = {"data": {"item": frame.to_dict(orient="records")}}
        if total is not None:
            try:
                result["data"]["total_num"] = int(total)
            except (TypeError, ValueError) as error:
                raise TdxProviderError("通达信 TotalNum 不是有效整数") from error
        return result

    def fetch_tick_data(
        self, thscode: str, date: str, startxh: int = 0, wantnum: int = 10
    ) -> dict:
        """获取指定交易日分笔；保留原始顺序，bs_flag 为 0买/1卖/2未知。"""
        if startxh < 0 or not 1 <= wantnum <= 2000:
            raise ValueError("startxh 不能为负，wantnum 必须在 1 到 2000 之间")
        code = self._stock_code(thscode)
        data = self._request(
            "get_tick_data",
            stock_code=code,
            date=self._date(date),
            startxh=startxh,
            wantnum=wantnum,
        )
        return self._intraday_result(data, code)

    def fetch_minute_data(
        self, thscode: str, date: str, field_list: Iterable[str] | None = None
    ) -> dict:
        """获取单日分时；field_list 使用 SDK 字段名，None/空列表获取全部字段。"""
        code = self._stock_code(thscode)
        fields = [field_list] if isinstance(field_list, str) else list(field_list or [])
        data = self._request(
            "get_minute_data", stock_code=code, date=self._date(date), field_list=fields
        )
        return self._intraday_result(data, code)

    def fetch_call_auction(self, thscode: str) -> dict:
        """获取当日开盘和收盘集合竞价的逐笔虚拟撮合数据。"""
        code = self._stock_code(thscode)
        return self._intraday_result(
            self._request("get_call_auction", stock_code=code), code
        )

    def fetch_index_constituents(self, index_code: str = "000300.SH") -> dict:
        """获取指数成份证券代码；指数应显式指定市场后缀。"""
        code = self._stock_code(index_code)
        data = self._request("get_zzgz_stocklist", index_code=code, list_type=0)
        if not isinstance(data, list):
            raise TdxProviderError("通达信指数成份股返回格式异常")
        codes = self._stock_codes(data) if data else []
        return {
            "data": {
                "item": [
                    {
                        "ticker": value,
                        "exchange": value.rsplit(".", 1)[1],
                        "source": self.source,
                    }
                    for value in codes
                ]
            }
        }

    def subscribe(
        self, stock_list: Iterable[str], callback: Callable[[str], Any]
    ) -> None:
        """订阅实时行情，callback 接收 SDK 原始 JSON 字符串。"""
        codes = self._stock_codes(stock_list)
        if not callable(callback):
            raise ValueError("callback 必须是可调用对象")
        # 订阅接口成功时返回 None，不能套用数据查询的 None 检查。
        try:
            self.client.subscribe(stock_list=codes, callback=callback)
        except Exception as error:
            raise TdxProviderError("通达信实时行情订阅失败") from error

    def unsubscribe(self, stock_list: Iterable[str]) -> None:
        """取消订阅。SDK 原生订阅连接由进程内所有实例共享。"""
        codes = self._stock_codes(stock_list)
        try:
            self.client.unsubscribe(stock_list=codes)
        except Exception as error:
            raise TdxProviderError("通达信实时行情取消订阅失败") from error

    @contextmanager
    def subscription(
        self, stock_list: Iterable[str], callback: Callable[[str], Any]
    ) -> Iterator[TdxProvider]:
        """使用 with 管理订阅，离开作用域或处理行情异常时自动取消。"""
        codes = self._stock_codes(stock_list)
        if not callable(callback):
            raise ValueError("callback 必须是可调用对象")
        try:
            self.subscribe(codes, callback)
            yield self
        finally:
            self.unsubscribe(codes)
