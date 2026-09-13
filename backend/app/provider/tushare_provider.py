"""使用 Tushare Pro 获取 A 股基础信息和历史行情。

默认通过中转地址请求；将 ``use_relay`` 设为 ``false`` 即可切换到
Tushare 官方地址。Token 只从构造参数或 ``backend/.env`` / 环境变量读取，
不会硬编码在源码中。
"""

from __future__ import annotations

from pathlib import Path


import pandas as pd
from pydantic_settings import BaseSettings, SettingsConfigDict
import tushare as ts

from ..utils.symbol import exchange_for, validate_symbol
from ..utils.date import timestamp_to_date

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


"""从环境变量和 backend/.env 读取 Tushare 配置"""


class TushareSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="TUSHARE_",
        extra="ignore",
    )
    private_token: str = ""
    relay_token: str = ""
    use_relay: bool = True
    relay_url: str = "https://t.xiaodefa.top"


def create_tushare_client(
    timeout: int = 30,
) -> None:

    # 获取配置
    settings = TushareSettings()
    private_token = settings.private_token
    relay_token = settings.relay_token
    use_relay = settings.use_relay

    if use_relay:
        # 返回中转client
        client = ts.pro_api(relay_token, timeout=timeout)
        client._DataApi__http_url = settings.relay_url
        return client
    else:
        # 返回官方client
        client = ts.pro_api(private_token, timeout=timeout)
        return client


class TushareProvider:
    """把 Tushare Pro 返回的数据适配为 app 服务使用的结构。"""

    source = "Tushare"

    _INTERVAL_MAP = {
        "1d": "D",
        "daily": "D",
        "1w": "W",
        "weekly": "W",
        "1mo": "M",
        "monthly": "M",
    }
    _ADJUST_MAP = {
        "": None,
        "none": None,
        "raw": None,
        "forward": "qfq",
        "qfq": "qfq",
        "backward": "hfq",
        "hfq": "hfq",
    }
    _EXCHANGE_MAP = {
        "SSE": "SH",
        "SZSE": "SZ",
        "BSE": "BJ",
    }

    def __init__(
        self,
        timeout: int = 30,
    ) -> None:

        self.pro = create_tushare_client(
            timeout=timeout,
        )

    @staticmethod
    def _ts_code(value: str) -> str:
        """把 app 支持的股票代码统一转换为 Tushare TS 代码。"""

        code = validate_symbol(value)
        return f"{code}.{exchange_for(code)}"

    def fetch_stock_list(self) -> dict:
        """获取沪、深、北交易所当前正常上市的全部 A 股。"""

        # exchange交易所 SSE上交所 SZSE深交所 BSE北交所
        result = self.pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,exchange,market",
        )

        return result

    def fetch_historical(
        self,
        thscode: str,
        start: int,
        end: int,
    ) -> dict:
        """获取历史行情，并返回 CNMarketService 能处理的字段和单位。"""

        result = self.pro.daily(
            ts_code=thscode,
            start_date=timestamp_to_date(start),
            end_date=timestamp_to_date(end),
        )

        if result is None or result.empty:
            return pd.DataFrame()

        return result

    def fetch_daily_basic(self) -> pd.DataFrame:
        """获取最新交易日动态每日指标，包含市值、市盈率等。"""

        result = self.pro.daily_basic(
            fields="ts_code,trade_date,total_mv",
        )
        if result is None or result.empty:
            return pd.DataFrame(columns=["symbol", "trade_date", "market_cap"])

        # 格式化symbol
        result["symbol"] = result["ts_code"]
        result["trade_date"] = pd.to_datetime(
            result["trade_date"], format="%Y%m%d", errors="coerce"
        ).dt.date
        # tushare daily_basic.total_mv 总市值 （万元） 的单位是万元，策略统一使用元。
        result["market_cap"] = (
            pd.to_numeric(result["total_mv"], errors="coerce") * 10000
        )

        return (
            # 去掉 market_cap 字段没有值的
            # 去重 symbol 字段的值，有重复的用最后一个
            result.dropna(subset=["trade_date", "market_cap"])
            .drop_duplicates(subset="symbol", keep="last")[
                ["symbol", "trade_date", "market_cap"]
            ]
            .reset_index(drop=True)
        )

    # 通用行情接口
    def fetch_pro_bar(
        self,
        thscode: str,
        start: int,
        end: int,
        interval: str = "1d",
        adjust: str = "forward",
        offset: int = 0,
    ) -> dict:
        """获取历史行情，并返回 CNMarketService 能处理的字段和单位。"""

        try:
            frequency = self._INTERVAL_MAP[interval.lower()]
        except KeyError as error:
            raise ValueError(f"Tushare 不支持行情周期: {interval!r}") from error

        try:
            adjustment = self._ADJUST_MAP[adjust.lower()]
        except KeyError as error:
            raise ValueError(f"Tushare 不支持复权方式: {adjust!r}") from error

        if offset < 0:
            raise ValueError("offset 不能小于 0")

        result = ts.pro_bar(
            api=self.pro,
            ts_code=self._ts_code(thscode),
            start_date=timestamp_to_date(start),
            end_date=timestamp_to_date(end),
            asset="E",
            freq=frequency,
            adj=adjustment,
        )

        print(result)

        if result is None or result.empty:
            return pd.DataFrame()

        return result
