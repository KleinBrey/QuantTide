"""获取 A 股历史热度排名；通过 lookback_days 指定自然日范围。"""

from backend.app.config.config import get_settings
from backend.app.database import DuckDBDatabase
from backend.app.provider.hithink_provider import HithinkProvider
from backend.app.repository import DailyHotRepository, DailyStockRepository
from backend.app.services import CNMarketService


def sync_daily_hot(lookback_days: int = 365) -> int:
    """补齐最近指定自然日范围（含今天）的热度排名。"""
    if lookback_days <= 0:
        raise ValueError("lookback_days 必须大于 0")

    settings = get_settings()
    database = DuckDBDatabase(settings.database_path)
    database.initialize()
    service = CNMarketService(
        hithink_provider=HithinkProvider(),
        daily_stock_repository=DailyStockRepository(database),
        daily_hot_repository=DailyHotRepository(database),
    )
    return service.update_daily_hot_history(
        lookback_days=lookback_days,
        max_workers=settings.sync_workers,
    )


def main() -> None:
    # 直接运行时显示菜单；API 和定时任务直接调用同步函数。
    print("""
        请选择要执行的任务：

        1. 更新最近 60 日A 股热度排名
        2. 更新最近 365 日A 股热度排名
        e. 退出
      """)
    choice = input("请输入选项: ").strip().lower()
    if choice == "e":
        print("退出")
        return
    days = {"1": 60, "2": 365}.get(choice)
    if days is None:
        print(f"无效选项: {choice}")
        return
    sync_daily_hot(lookback_days=days)


if __name__ == "__main__":
    main()
