"""通过 Yahoo Finance 获取港股、美股历史 K 线，无需本地 OpenD。"""

from __future__ import annotations

import re
import time
from datetime import timedelta
from typing import Any, Callable

import pandas as pd

from ..utils.symbol import normalize_daily_bar_symbol


class YFinanceProviderError(RuntimeError):
    """Yahoo Finance 请求失败或行情格式异常。"""


class YFinanceProvider:
    """将 yfinance 行情适配为 Provider 通用的 ``data.item`` 结构。"""

    source = "YFinance"
    _INTERVAL_MAP = {
        "1d": "1d", "daily": "1d",
        "1w": "1wk", "weekly": "1wk",
        "1mo": "1mo", "monthly": "1mo",
    }
    # Yahoo 自动复权不等同于 Futu 前复权；不将 back_adjust 冒充后复权。
    _ADJUST_MAP = {"": False, "none": False, "raw": False,
                   "forward": True, "qfq": True}

    def __init__(
        self,
        timeout: float = 30,
        *,
        max_attempts: int = 3,
        retry_delay: float = 2,
        ticker_factory: Callable[..., Any] | None = None,
    ) -> None:
        if timeout <= 0 or max_attempts < 1 or retry_delay < 0:
            raise ValueError("timeout、max_attempts 必须为正，retry_delay 不能为负")
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay
        self._ticker_factory = ticker_factory

    @staticmethod
    def _market_symbol(value: str) -> tuple[str, str]:
        """返回 Yahoo 代码和交易所时区；内部股票代码不随数据源改变。"""
        symbol = str(value).strip().upper()
        if symbol.startswith("HK.") or symbol.endswith(".HK") or symbol.isdigit():
            code = normalize_daily_bar_symbol(symbol, "hk-share")[:-3]
            return f"{int(code):04d}.HK", "Asia/Hong_Kong"
        if symbol.startswith(("SH.", "SZ.", "BJ.")) or symbol.endswith((".SH", ".SZ", ".BJ")):
            raise ValueError("YFinance Provider 仅支持港股和美股")
        code = symbol.removeprefix("US.").removesuffix(".US")
        # .A 也可能是股份类别（BRK.A），不能按交易所后缀直接移除。
        if code.endswith((".O", ".N")):
            code = code[:-2]
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]*", code) or code.endswith("."):
            raise ValueError(f"不支持的美股代码: {value!r}")
        return code.replace(".", "-"), "America/New_York"

    def fetch_historical(
        self,
        thscode: str,
        start: int,
        end: int,
        interval: str = "1d",
        adjust: str = "forward",
        offset: int = 0,
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """获取历史 K 线；毫秒时间戳按市场日期解释，首尾日期均包含。

        ``date_ms`` 沿用项目约定，以上海时区午夜编码交易日，而非实际
        开盘时刻。``turnover`` 为 None；Yahoo 不提供日线真实成交额。
        ``raw`` 仅关闭 yfinance 自动复权，不承诺还原拆股前的原始价格。
        """
        if start > end:
            raise ValueError("start 不能晚于 end")
        if offset < 0:
            raise ValueError("offset 不能小于 0")
        try:
            period = self._INTERVAL_MAP[interval.lower()]
        except KeyError as error:
            raise ValueError(f"YFinance 不支持行情周期: {interval!r}") from error
        try:
            auto_adjust = self._ADJUST_MAP[adjust.lower()]
        except KeyError as error:
            raise ValueError(f"YFinance 不支持复权方式: {adjust!r}") from error
        symbol, timezone = self._market_symbol(thscode)
        start_date = pd.to_datetime(start, unit="ms", utc=True).tz_convert(timezone).date()
        end_date = pd.to_datetime(end, unit="ms", utc=True).tz_convert(timezone).date()

        factory = self._ticker_factory
        if factory is None:
            import yfinance as yf

            factory = yf.Ticker
        for attempt in range(self.max_attempts):
            try:
                frame = factory(symbol).history(
                    start=start_date.isoformat(),
                    # Yahoo 的 end 不包含当天。
                    end=(end_date + timedelta(days=1)).isoformat(),
                    interval=period,
                    auto_adjust=auto_adjust,
                    back_adjust=False,
                    actions=False,
                    repair=False,
                    prepost=False,
                    keepna=True,
                    timeout=self.timeout,
                    raise_errors=True,
                )
                break
            except Exception as error:
                if attempt + 1 == self.max_attempts:
                    raise YFinanceProviderError(f"Yahoo Finance {symbol} 获取失败: {error}") from error
                time.sleep(self.retry_delay * 2**attempt)

        if not isinstance(frame, pd.DataFrame):
            raise YFinanceProviderError(f"Yahoo Finance {symbol} 返回格式异常")
        if frame.empty:
            return {"data": {"item": []}}
        column_map = {
            "Open": "open_price", "High": "high_price",
            "Low": "low_price", "Close": "close_price", "Volume": "volume",
        }
        missing = set(column_map).difference(frame.columns)
        if missing:
            raise YFinanceProviderError(f"Yahoo Finance 日 K 数据缺少字段: {', '.join(sorted(missing))}")
        result = frame[list(column_map)].rename(columns=column_map).copy()
        dates = pd.DatetimeIndex(result.index)
        if dates.tz is not None:
            dates = dates.tz_convert(timezone)
        trade_dates = dates.date
        result["date_ms"] = [
            int(pd.Timestamp(day, tz="Asia/Shanghai").timestamp() * 1000)
            for day in trade_dates
        ]
        result = result[(trade_dates >= start_date) & (trade_dates <= end_date)]
        for column in column_map.values():
            result[column] = pd.to_numeric(result[column], errors="raise")
        # 保留有实际行情的记录；公司行动空行不能写入 NOT NULL 的 OHLC。
        result = result.dropna(subset=list(column_map.values()))
        result = result.sort_values("date_ms").drop_duplicates("date_ms", keep="last")
        result["turnover"] = None
        result["source"] = self.source
        return {"data": {"item": result.iloc[offset:].to_dict(orient="records")}}
