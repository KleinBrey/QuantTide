import requests

import time

import random

import pandas as pd

from pprint import pprint

BASE_URL: str = "https://fuyao.aicubes.cn"

HITHINK_FINANCE_API_KEY: str = "sk-fuyao-ubQXGmGz8oPFVwDZ1wITPlbyTtPJwErA"


session = requests.Session()


session.headers.update({"X-api-key": HITHINK_FINANCE_API_KEY})

"""
  同花顺接口统一调用方法
"""


class HithinkProvider:

    def fetch_hot_stock_rank_trend(
        self, thscode: str, start_date: str, end_date: str
    ) -> list[dict]:
        """获取单只股票的历史每日热度排名，日期格式为 YYYY-MM-DD。"""
        # 每次请求使用独立连接，避免多线程共用全局 Session。
        response = requests.get(
            f"{BASE_URL}/api/a-share/special-data/hot-stock-rank-trend",
            headers={"X-api-key": HITHINK_FINANCE_API_KEY},
            params={
                "thscode": thscode,
                "start_date": start_date,
                "end_date": end_date,
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        if result["code"] != 0:
            raise RuntimeError(f"接口错误 {result['code']}: {result.get('message')}")
        return result["data"]["item"]

    @staticmethod
    def get(url: str, params: dict) -> dict:
        query_url = f"{BASE_URL}/{url}"
        try:
            response = session.get(query_url, params=params)
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP 错误：{http_err}")
        except requests.exceptions.ConnectionError as conn_err:
            print(f"连接错误：{conn_err}")
        except requests.exceptions.Timeout as timeout_err:
            print(f"请求超时：{timeout_err}")
        except requests.exceptions.RequestException as req_err:
            print(f"请求异常：{req_err}")
        except ValueError as json_err:
            print(f"JSON 解析错误：{json_err}")
        else:
            return response.json()

    # 全市场股票列表获取
    def fetch_stock_list(self) -> dict:
        url = "api/meta/tickers/list"
        # 初始化分页偏移量
        offset = 0
        # 定义每页返回的股票数量默认是1000
        limit = 10000
        params = {
            "asset_type": "a-share",  # 资产类型过滤：A 股
            "limit": limit,  # 每页数量
            "offset": offset,  # 分页偏移
        }
        result = self.get(url, params)
        return result["data"]["item"]

    # 获取当前股票快照
    def fetch_snapshot(self, thscode: str, limit: int = 100, offset: int = 0) -> dict:
        url = "api/a-share/prices/snapshot"
        params = {"thscodes": thscode, limit: limit, offset: offset}
        result = self.get(url, params)
        return result

    # 获取股票历史日线数据
    def fetch_historical(
        self,
        thscode: str,
        start: int,
        end: int,
        interval: str = "1d",
        adjust: str = "forward",
        offset: int = 0,
    ) -> dict:
        url = "api/a-share/prices/historical"
        params = {
            "thscode": thscode,
            "interval": interval,
            "start": start,
            "end": end,
            "adjust": adjust,
            "offset": offset,
        }
        # 随机延迟0.2～0.4秒
        time.sleep(random.uniform(0.2, 0.4))
        result = self.get(url, params)
        return result["data"]["item"]
