"""应用配置管理模块。

使用 Pydantic Settings 管理应用程序的所有配置参数，包括数据库连接、API 密钥、
调度器设置等。支持从 .env 文件加载环境变量。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录：从当前文件所在目录往上三级
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """应用配置类"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / "backend" / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用名称
    app_name: str = "Quant Tide"

    # API 路由前缀
    api_prefix: str = "/api"

    # DuckDB 数据库路径
    database_path: Path = Field(default=PROJECT_ROOT / "data" / "cn_market.duckdb")
    hk_database_path: Path = Field(
        default=PROJECT_ROOT / "data" / "hk_market.duckdb"
    )
    us_database_path: Path = Field(
        default=PROJECT_ROOT / "data" / "us_market.duckdb"
    )

    # 跨域 # CORS 允许的源
    cors_origins_list: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    # 是否启用定时任务调度器
    scheduler_enabled: bool = True

    # 调度器时区
    scheduler_timezone: str = "Asia/Shanghai"

    # 数据同步的并发工作进程数
    sync_workers: int = 4


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取应用配置单例。

    使用 LRU 缓存确保在整个应用生命周期中只创建一个 Settings 实例。
    这样可以提高性能，避免重复解析 .env 文件。

    Returns:
        全局唯一的 Settings 实例
    """
    return Settings()
