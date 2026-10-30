"""通过币安现货 REST API 获取公开行情，无需 API Key。"""

from __future__ import annotations

import requests


class BinanceProvider:
    """获取币安行情：多条记录返回列表，单个快照或盘口返回字典。"""

    source = "Binance"
    _INTERVALS = {
        "1s",
        "1m",
        "3m",
        "5m",
        "15m",
        "30m",
        "1h",
        "2h",
        "4h",
        "6h",
        "8h",
        "12h",
        "1d",
        "3d",
        "1w",
        "1M",
    }
    _INTERVAL_MAP = {
        "daily": "1d",
        "weekly": "1w",
        "monthly": "1M",
        "1mo": "1M",
    }

    def __init__(
        self, timeout: float = 30, *, base_url: str = "https://api.binance.com"
    ) -> None:
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict) -> dict | list:
        """统一设置超时；HTTP 错误直接向调用方抛出。"""
        response = requests.get(
            f"{self.base_url}/api/v3/{path}", params=params, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _symbol(thscode: str) -> str:
        """使用币安交易对代码，例如 BTCUSDT。"""
        symbol = thscode.strip().upper()
        if not symbol:
            raise ValueError("交易对代码不能为空")
        return symbol

    def fetch_historical(
        self,
        thscode: str,
        start: int,
        end: int,
        interval: str = "1d",
        adjust: str = "none",
        offset: int = 0,
    ) -> list[dict]:
        """按开盘时间获取 K 线，start/end 为毫秒时间戳，包含首尾。

        币安现货不复权，仅接受 none/raw/空字符串。date_ms 保留实际
        UTC 开盘时间；volume 是基础币数量，turnover 是计价币成交额。
        返回结果可能包含尚未收盘的当前 K 线。
        """
        if start > end:
            raise ValueError("start 不能晚于 end")
        if offset < 0:
            raise ValueError("offset 不能小于 0")
        if adjust.lower() not in {"", "none", "raw"}:
            raise ValueError("币安现货不支持复权，请使用 none 或 raw")
        # 不能统一转小写：币安的 1m 表示分钟，1M 表示月。
        period = self._INTERVAL_MAP.get(interval, interval)
        if period not in self._INTERVALS:
            raise ValueError(f"Binance 不支持行情周期: {interval!r}")

        symbol = self._symbol(thscode)
        items = []
        cursor = start
        while cursor <= end:
            rows = self._get(
                "klines",
                {
                    "symbol": symbol,
                    "interval": period,
                    "startTime": cursor,
                    "endTime": end,
                    "limit": 1000,
                },
            )
            if not rows:
                break
            for row in rows:
                items.append(
                    {
                        "date_ms": int(row[0]),
                        "open_price": float(row[1]),
                        "high_price": float(row[2]),
                        "low_price": float(row[3]),
                        "close_price": float(row[4]),
                        "volume": float(row[5]),
                        "turnover": float(row[7]),
                        "source": self.source,
                    }
                )
            if len(rows) < 1000:
                break
            # 开盘时间唯一，向后移动 1 毫秒即可避免重复，也适用于不等长的月 K。
            cursor = int(rows[-1][0]) + 1

        return items[offset:]

    def fetch_snapshot(self, thscode: str) -> dict:
        """获取单个交易对的滚动 24 小时行情，保留币安原始字段。"""
        row = self._get("ticker/24hr", {"symbol": self._symbol(thscode)})
        return {**row, "source": self.source}

    def fetch_depth(self, thscode: str, limit: int = 100) -> dict:
        """获取盘口；bids/asks 每项为 [价格, 数量]，保留原始字符串精度。"""
        if not 1 <= limit <= 5000:
            raise ValueError("limit 必须在 1 到 5000 之间")
        row = self._get("depth", {"symbol": self._symbol(thscode), "limit": limit})
        return {**row, "source": self.source}

    def fetch_trades(self, thscode: str, limit: int = 500) -> list[dict]:
        """获取近期成交，保留币安原始字段；time 为毫秒时间戳。"""
        if not 1 <= limit <= 1000:
            raise ValueError("limit 必须在 1 到 1000 之间")
        rows = self._get("trades", {"symbol": self._symbol(thscode), "limit": limit})
        return [{**row, "source": self.source} for row in rows]
