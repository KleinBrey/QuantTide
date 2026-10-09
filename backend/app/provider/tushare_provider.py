"""使用 Tushare Pro 获取 A 股基础信息和历史行情。

默认通过中转地址请求；将 ``use_relay`` 设为 ``false`` 即可切换到
Tushare 官方地址。Token 只从构造参数或 ``backend/.env`` / 环境变量读取，
不会硬编码在源码中。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
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

    def fetch_trade_dates(self, start: date, end: date) -> list[date]:
        """读取交易所日历，避免用工作日猜测交易日。"""
        result = self.pro.trade_cal(
            exchange="SSE",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            is_open="1",
            fields="cal_date,is_open",
        )
        if result is None or result.empty:
            return []
        dates = pd.to_datetime(
            result.loc[result["is_open"].astype(str) == "1", "cal_date"],
            format="%Y%m%d",
            errors="raise",
        ).dt.date
        return sorted(set(day for day in dates if start <= day <= end))

    def latest_trade_date(self) -> date:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        days = self.fetch_trade_dates(today - timedelta(days=60), today)
        if not days:
            raise RuntimeError("交易日历没有返回最近交易日")
        return days[-1]

    def fetch_stock_list(self, trade_date: date | None = None) -> pd.DataFrame:
        """bak_basic 每天完整历史股票池；不使用 stock_basic 当前名称回填。"""
        day = trade_date or self.latest_trade_date()
        result = self.pro.bak_basic(
            trade_date=day.strftime("%Y%m%d"),
            fields="trade_date,ts_code,name,list_date",
        )
        if result is None or result.empty:
            return pd.DataFrame()
        if len(result) >= 7000:
            raise RuntimeError(
                f"{day} 股票池达到接口 7000 条上限，拒绝保存可能截断的快照"
            )
        result = result.copy()
        result["trade_date"] = pd.to_datetime(
            result["trade_date"], format="%Y%m%d", errors="raise"
        ).dt.date
        if result["trade_date"].isna().any() or not result["trade_date"].eq(day).all():
            raise ValueError("历史股票池返回的日期与请求日期不一致")
        if (
            result[["ts_code", "name"]].isna().any().any()
            or result["ts_code"].duplicated().any()
        ):
            raise ValueError("历史股票池存在空字段或重复代码")
        # bak_basic 可能包含尚未上市股票；未知上市日不能视作已上市。
        listed = pd.to_datetime(
            result["list_date"], format="%Y%m%d", errors="coerce"
        ).dt.date
        result = result.loc[listed.notna() & (listed <= day)].copy()
        result["exchange"] = result["ts_code"].str.rsplit(".", n=1).str[-1]
        code = result["ts_code"].str.split(".").str[0]
        result["market"] = "主板"
        result.loc[code.str.startswith(("300", "301")), "market"] = "创业板"
        result.loc[code.str.startswith(("688", "689")), "market"] = "科创板"
        result.loc[result["exchange"] == "BJ", "market"] = "北交所"
        if not result["exchange"].isin(["SH", "SZ", "BJ"]).all():
            raise ValueError("历史股票池包含未知交易所")
        return result

    def fetch_daily_bar(self, trade_date: date) -> pd.DataFrame:
        """获取指定交易日全市场未复权日 K，保留 Tushare 原始字段和单位。"""
        result = self.pro.daily(trade_date=trade_date.strftime("%Y%m%d"))
        if result is None or result.empty:
            return pd.DataFrame()
        if len(result) >= 6000:
            raise RuntimeError(
                f"{trade_date} 日 K 达到接口 6000 条上限，拒绝保存可能截断的数据"
            )
        dates = pd.to_datetime(
            result["trade_date"], format="%Y%m%d", errors="raise"
        ).dt.date
        if dates.isna().any() or not dates.eq(trade_date).all():
            raise ValueError("日 K 返回的日期与请求日期不一致")

        return result

    def fetch_daily_basic(self, trade_date: date | None = None) -> pd.DataFrame:
        """获取指定交易日的每日指标；未指定日期时获取最新数据。"""

        parameters = {"fields": "ts_code,trade_date,total_mv"}
        if trade_date is not None:
            parameters["trade_date"] = trade_date.strftime("%Y%m%d")

        result = self.pro.daily_basic(**parameters)
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
            .drop_duplicates(subset=["symbol", "trade_date"], keep="last")[
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
