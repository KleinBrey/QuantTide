"""同花顺问财自然语言选股的简单 Provider。"""

from __future__ import annotations

import secrets

from pathlib import Path

from typing import Any

import pandas as pd

import requests

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class IwencaiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="IWENCAI_",
        extra="ignore",
    )

    api_key: str = ""
    api_key_backup: str = ""
    api_key_weibo: str = ""
    base_url: str = "https://openapi.iwencai.com"


class IwencaiError(RuntimeError):
    """问财请求失败或返回格式异常。"""


class IwencaiProvider:
    """使用自然语言条件查询问财选股结果。"""

    def __init__(
        self,
        timeout: int = 60,
    ) -> None:
        settings = IwencaiSettings()
        self.api_keys = [
            key
            for key in (
                settings.api_key_weibo.strip(),
                settings.api_key_backup.strip(),
                settings.api_key.strip(),
            )
            if key
        ]
        # 当前使用的Key下标
        self.current_api_key_index = 0
        self.base_url = settings.base_url
        self.timeout = max(1, timeout)
        self.session = requests.Session()

    def query(
        self,
        query: str,
        page_size: int = 50,
        max_pages: int = 100,
    ) -> list[dict[str, Any]]:
        """分页查询问财，并返回全部选股记录。"""

        normalized_query = " ".join(query.split())
        if not normalized_query:
            raise ValueError("查询条件不能为空")
        if not self.api_keys:
            raise IwencaiError("未配置问财 API Key")
        if page_size < 1 or max_pages < 1:
            raise ValueError("page_size 和 max_pages 必须大于 0")

        rows: list[dict[str, Any]] = []
        expected_total: int | None = None

        for page in range(1, max_pages + 1):
            response = self._request_page(normalized_query, page, page_size)
            if page == 1:
                try:
                    expected_total = int(response.get("code_count", 0))
                except (TypeError, ValueError):
                    expected_total = None

            page_rows = response.get("datas") or []
            if not isinstance(page_rows, list):
                raise IwencaiError(f"第 {page} 页 datas 字段不是列表")
            rows.extend(item for item in page_rows if isinstance(item, dict))

            if not page_rows:
                break
            if expected_total is not None and len(rows) >= expected_total:
                break
            if len(page_rows) < page_size:
                break
        else:
            if expected_total is None or len(rows) < expected_total:
                raise IwencaiError(f"达到最大分页数 {max_pages}，结果尚未获取完整")

        return rows

    def _request_page(
        self,
        query: str,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        payload = {
            "query": query,
            "page": str(page),
            "limit": str(page_size),
            "is_cache": "1",
            "expand_index": "true",
        }

        last_error: IwencaiError | None = None
        # 最多尝试列表长度
        for _ in self.api_keys:
            api_key = self.api_keys[self.current_api_key_index]
            try:
                return self._send_request(payload, api_key)
            except IwencaiError as exc:
                last_error = exc
                self.current_api_key_index = (self.current_api_key_index + 1) % len(
                    self.api_keys
                )

        raise IwencaiError(f"所有问财 API Key 均请求失败：{last_error}") from last_error

    def _send_request(
        self,
        payload: dict[str, str],
        api_key: str,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Claw-Call-Type": "normal",
            "X-Claw-Skill-Id": "hithink-astock-selector",
            "X-Claw-Skill-Version": "1.0.0",
            "X-Claw-Plugin-Id": "none",
            "X-Claw-Plugin-Version": "none",
            "X-Claw-Trace-Id": secrets.token_hex(32),
        }

        try:
            response = self.session.post(
                f"{self.base_url}/v1/query2data",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
        except requests.HTTPError as exc:
            detail = exc.response.text.strip()
            raise IwencaiError(
                f"问财请求失败（HTTP {exc.response.status_code}）：{detail}"
            ) from exc
        except requests.RequestException as exc:
            raise IwencaiError(f"问财请求失败：{exc}") from exc
        except ValueError as exc:
            raise IwencaiError("问财返回了无法解析的内容") from exc

        if not isinstance(result, dict):
            raise IwencaiError("问财返回格式异常")
        return result

    """
        API调用
    """

    def fetch_hot_rank(self) -> pd.DataFrame:
        """获取 A 股热度列表。"""
        data = self.query(
            "A股热度排名前1000",
            page_size=50,
        )

        return self.format_hot_rank(data)

    def fetch_hk_hot_rank(self) -> pd.DataFrame:
        """获取港股关注度排名前 50。"""
        data = self.query(
            "港股关注度排名前50",
            page_size=50,
        )
        frame = pd.DataFrame(data)

        hot_col = next(col for col in frame.columns if col.startswith("个股热度"))

        frame = frame.rename(
            columns={
                "股票代码": "symbol",
                "股票简称": "name",
                "收盘价": "price",
                "最新涨跌幅": "change_pct",
                hot_col: "hot_rank",
            }
        )

        # 有时候港股数据没有 price 或 change_pct 字段，补充为缺失值。
        for col in ["price", "change_pct"]:
            if col not in frame.columns:
                frame[col] = pd.NA

        return frame

    def fetch_us_hot_rank(self) -> pd.DataFrame:
        """获取美股关注度排名前 50。"""
        data = self.query(
            "美股关注度排名前50",
            page_size=50,
        )

        return self.format_hot_rank(data)

    @staticmethod
    def format_hot_rank(data: list[dict[str, Any]]) -> pd.DataFrame:
        """将问财热度结果转换为统一字段。"""

        frame = pd.DataFrame(data)

        hot_col = next(col for col in frame.columns if col.startswith("个股热度"))

        frame = frame.rename(
            columns={
                "股票代码": "symbol",
                "股票简称": "name",
                "最新价": "price",
                "最新涨跌幅": "change_pct",
                hot_col: "hot_rank",
            }
        )

        return frame
