"""通过本机 Futu OpenD 获取行情数据。"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator

import pandas as pd

from ..utils.symbol import exchange_for


class FutuProviderError(RuntimeError):
    """Futu OpenD 连接失败或接口返回错误。"""


class FutuProvider:
    """把 Futu OpenD 行情适配为现有 Provider 使用的数据结构。"""

    source = "Futu"

    _A_SHARE_MARKETS = ("SH", "SZ")
    _INTERVAL_MAP = {
        "1d": "K_DAY",
        "daily": "K_DAY",
        "1w": "K_WEEK",
        "weekly": "K_WEEK",
        "1mo": "K_MON",
        "monthly": "K_MON",
    }
    _ADJUST_MAP = {
        "": "None",
        "none": "None",
        "raw": "None",
        "forward": "qfq",
        "qfq": "qfq",
        "backward": "hfq",
        "hfq": "hfq",
    }
    _CODE_PATTERN = re.compile(r"^(?:(SH|SZ)\.)?(\d{6})(?:\.(SH|SZ))?$")
    _SNAPSHOT_MARKETS = ("SH", "SZ", "HK", "US")
    _OTHER_FUTU_MARKETS = (
        "HK_FUTURE",
        "SG",
        "JP",
        "AU",
        "MY",
        "CA",
        "FX",
        "CC",
        "EC",
    )
    _US_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11111,
        *,
        is_encrypt: bool | None = None,
        context_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not host.strip():
            raise ValueError("Futu OpenD host 不能为空")
        if not 1 <= port <= 65535:
            raise ValueError("Futu OpenD port 必须在 1 到 65535 之间")

        self.host = host.strip()
        self.port = port
        self.is_encrypt = is_encrypt
        self._context_factory = context_factory
        self._active_quote_context: Any | None = None

    @staticmethod
    def set_console_logging(enabled: bool) -> None:
        """控制 Futu SDK 是否向当前进程的控制台输出日志。"""

        from futu import SysConfig

        SysConfig.enable_console_log(enabled)

    @contextmanager
    def session(self) -> Iterator[FutuProvider]:
        """在多个 Provider 请求之间复用同一个 Futu 行情连接。"""

        if self._active_quote_context is not None:
            yield self
            return

        with self._new_quote_context() as quote_context:
            self._active_quote_context = quote_context
            try:
                yield self
            finally:
                self._active_quote_context = None

    @contextmanager
    def _quote_context(self) -> Iterator[Any]:
        """优先复用会话连接，否则为单次请求创建连接。"""

        if self._active_quote_context is not None:
            yield self._active_quote_context
            return

        with self._new_quote_context() as quote_context:
            yield quote_context

    @contextmanager
    def _new_quote_context(self) -> Iterator[Any]:
        """创建并可靠关闭一个新的行情连接。"""

        factory = self._context_factory
        if factory is None:
            # Futu SDK 导入时会初始化自己的日志目录。延迟导入可避免系统仅加载
            # Provider 注册表时就产生文件和线程等副作用。
            from futu import OpenQuoteContext

            factory = OpenQuoteContext

        context = factory(
            host=self.host,
            port=self.port,
            is_encrypt=self.is_encrypt,
        )
        try:
            yield context
        finally:
            context.close()

    @classmethod
    def _futu_code(cls, value: str) -> str:
        """将 600519、600519.SH 或 SH.600519 转为 Futu 代码。"""

        normalized = str(value).strip().upper()
        match = cls._CODE_PATTERN.fullmatch(normalized)
        if match is None:
            raise ValueError(f"不支持的 A 股代码格式: {value!r}")

        prefix, code, suffix = match.groups()
        if prefix and suffix:
            raise ValueError(f"A 股代码不能同时包含市场前缀和后缀: {value!r}")

        market = prefix or suffix or exchange_for(code)
        if market not in cls._A_SHARE_MARKETS:
            raise ValueError(f"Futu Provider 暂不支持该 A 股市场: {market}")
        return f"{market}.{code}"

    @classmethod
    def _market_code(cls, value: object) -> str:
        """将项目代码转换为 Futu 行情接口使用的市场前缀格式。"""

        normalized = str(value).strip().upper()
        if not normalized:
            raise ValueError("Futu 股票代码不能为空")

        unsupported_market = next(
            (
                market
                for market in cls._OTHER_FUTU_MARKETS
                if normalized.startswith(f"{market}.")
                or normalized.endswith(f".{market}")
            ),
            None,
        )
        if unsupported_market:
            raise ValueError(f"Futu Provider 暂不支持 {unsupported_market} 市场")

        prefix_market = next(
            (
                market
                for market in cls._SNAPSHOT_MARKETS
                if normalized.startswith(f"{market}.")
            ),
            None,
        )
        suffix_market = next(
            (
                market
                for market in cls._SNAPSHOT_MARKETS
                if normalized.endswith(f".{market}")
            ),
            None,
        )
        if prefix_market and suffix_market:
            raise ValueError(f"股票代码不能同时包含市场前缀和后缀: {value!r}")

        if prefix_market:
            market = prefix_market
            code = normalized[len(prefix_market) + 1 :]
        elif suffix_market:
            market = suffix_market
            code = normalized[: -(len(suffix_market) + 1)]
        elif normalized.isdigit() and len(normalized) == 6:
            return cls._futu_code(normalized)
        elif normalized.isdigit() and len(normalized) <= 5:
            market = "HK"
            code = normalized.zfill(5)
        else:
            market = "US"
            code = normalized

        if market in cls._A_SHARE_MARKETS:
            return cls._futu_code(f"{market}.{code}")
        if market == "HK":
            if not code.isdigit() or not 1 <= len(code) <= 5:
                raise ValueError(f"不支持的港股代码格式: {value!r}")
            return f"HK.{code.zfill(5)}"
        if not cls._US_CODE_PATTERN.fullmatch(code):
            raise ValueError(f"不支持的美股代码格式: {value!r}")
        return f"US.{code}"

    @staticmethod
    def _check_result(operation: str, ret_code: int, data: Any) -> pd.DataFrame:
        if ret_code != 0:
            raise FutuProviderError(f"Futu OpenD {operation}失败: {data}")
        if not isinstance(data, pd.DataFrame):
            raise FutuProviderError(f"Futu OpenD {operation}返回格式异常")
        return data

    @staticmethod
    def _timestamp_to_date(timestamp_ms: int) -> str:
        timestamp = pd.to_datetime(timestamp_ms, unit="ms", utc=True)
        return timestamp.tz_convert("Asia/Shanghai").strftime("%Y-%m-%d")

    def fetch_stock_list(
        self,
        code_list: Iterable[str] | None = None,
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """获取沪深 A 股列表；传入代码时只获取指定股票。"""

        frames: list[pd.DataFrame] = []
        normalized_codes = (
            [self._futu_code(code) for code in code_list]
            if code_list is not None
            else None
        )
        if normalized_codes == []:
            return {"data": {"item": []}}

        with self._quote_context() as quote_context:
            if normalized_codes is not None:
                ret_code, data = quote_context.get_stock_basicinfo(
                    "SH",
                    stock_type="STOCK",
                    code_list=normalized_codes,
                )
                frames.append(self._check_result("获取股票信息", ret_code, data))
            else:
                for market in self._A_SHARE_MARKETS:
                    ret_code, data = quote_context.get_stock_basicinfo(
                        market,
                        stock_type="STOCK",
                    )
                    frames.append(
                        self._check_result(f"获取 {market} 股票列表", ret_code, data)
                    )

        if not frames or all(frame.empty for frame in frames):
            return {"data": {"item": []}}

        frame = pd.concat(frames, ignore_index=True)
        required_columns = {"code", "name"}
        missing_columns = required_columns.difference(frame.columns)
        if missing_columns:
            missing_text = ", ".join(sorted(missing_columns))
            raise FutuProviderError(f"Futu 股票列表缺少字段: {missing_text}")

        if "delisting" in frame.columns:
            frame = frame.loc[~frame["delisting"].fillna(False).astype(bool)].copy()

        code_parts = frame["code"].str.extract(r"^(SH|SZ)\.(\d{6})$")
        frame = frame.loc[code_parts[0].notna()].copy()
        code_parts = code_parts.loc[frame.index]
        frame["ticker"] = code_parts[1].values
        frame["exchange"] = code_parts[0].values
        frame["source"] = self.source

        items = frame[["ticker", "name", "exchange", "source"]]
        return {"data": {"item": items.to_dict(orient="records")}}

    def fetch_snapshot(
        self,
        thscode: str | Iterable[str],
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """获取最多 400 个 A 股、港股或美股标的的市场快照。"""

        values = [thscode] if isinstance(thscode, str) else list(thscode)
        # Futu 接口要求 MARKET.CODE 格式，并对重复代码自动去重。
        # 在这里先做同样的去重，避免重复输入误触 400 个标的限制。
        codes = list(dict.fromkeys(self._market_code(value) for value in values))
        if not codes:
            return {"data": {"item": []}}
        if len(codes) > 400:
            raise ValueError("Futu 单次快照最多支持 400 个标的")

        with self._quote_context() as quote_context:
            ret_code, data = quote_context.get_market_snapshot(codes)
            frame = self._check_result("获取市场快照", ret_code, data).copy()

        if frame.empty:
            return {"data": {"item": []}}

        if "code" not in frame.columns:
            raise FutuProviderError("Futu 市场快照缺少字段: code")

        frame["source"] = self.source
        return {"data": {"item": frame.to_dict(orient="records")}}

    def fetch_hot_list(
        self,
        market: str = "US",
        count: int = 10,
        offset: int = 0,
    ) -> tuple[int, pd.DataFrame]:
        """获取港股或美股热议榜。"""

        normalized_market = market.strip().upper()
        if normalized_market not in {"HK", "US"}:
            raise ValueError("Futu 热议榜仅支持 HK 或 US 市场")
        if not 1 <= count <= 200:
            raise ValueError("count 必须在 1 到 200 之间")
        if offset < 0:
            raise ValueError("offset 不能小于 0")

        with self._quote_context() as quote_context:
            ret_code, data = quote_context.get_hot_list(
                market=normalized_market,
                count=count,
                offset=offset,
            )
            if ret_code != 0:
                raise FutuProviderError(f"Futu OpenD 获取热议榜失败: {data}")
            if not isinstance(data, tuple) or len(data) != 2:
                raise FutuProviderError("Futu OpenD 获取热议榜返回格式异常")

            all_count, frame = data
            frame = self._check_result("获取热议榜", ret_code, frame).copy()

        frame["source"] = self.source
        return int(all_count), frame

    def fetch_historical(
        self,
        thscode: str,
        start: int,
        end: int,
        interval: str = "1d",
        adjust: str = "forward",
        offset: int = 0,
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """分页获取 A 股、港股或美股历史 K 线。"""

        if offset < 0:
            raise ValueError("offset 不能小于 0")
        if start > end:
            raise ValueError("start 不能晚于 end")

        try:
            ktype = self._INTERVAL_MAP[interval.lower()]
        except KeyError as error:
            raise ValueError(f"Futu 不支持行情周期: {interval!r}") from error
        try:
            autype = self._ADJUST_MAP[adjust.lower()]
        except KeyError as error:
            raise ValueError(f"Futu 不支持复权方式: {adjust!r}") from error

        code = self._market_code(thscode)
        start_date = self._timestamp_to_date(start)
        end_date = self._timestamp_to_date(end)
        page_req_key = None
        frames: list[pd.DataFrame] = []

        with self._quote_context() as quote_context:
            while True:
                ret_code, data, page_req_key = quote_context.request_history_kline(
                    code=code,
                    start=start_date,
                    end=end_date,
                    ktype=ktype,
                    autype=autype,
                    max_count=1000,
                    page_req_key=page_req_key,
                )
                frames.append(self._check_result("获取历史 K 线", ret_code, data))
                if page_req_key is None:
                    break

        if not frames or all(frame.empty for frame in frames):
            return {"data": {"item": []}}

        frame = pd.concat(frames, ignore_index=True)
        column_map = {
            "time_key": "date",
            "open": "open_price",
            "high": "high_price",
            "low": "low_price",
            "close": "close_price",
            "volume": "volume",
            "turnover": "turnover",
        }
        missing_columns = set(column_map).difference(frame.columns)
        if missing_columns:
            missing_text = ", ".join(sorted(missing_columns))
            raise FutuProviderError(f"Futu 历史 K 线缺少字段: {missing_text}")

        result = frame[list(column_map)].rename(columns=column_map).copy()
        result = result.iloc[offset:].reset_index(drop=True)
        trade_dates = pd.to_datetime(result.pop("date"), errors="raise")
        shanghai_dates = trade_dates.dt.tz_localize("Asia/Shanghai")
        result["date_ms"] = shanghai_dates.map(
            lambda value: int(value.timestamp() * 1000)
        )

        for column in (
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "turnover",
        ):
            result[column] = pd.to_numeric(result[column], errors="raise")

        result["source"] = self.source
        return {"data": {"item": result.to_dict(orient="records")}}
