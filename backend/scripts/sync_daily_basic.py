"""同步 A 股每日指标；通过 lookback_days 指定自然日范围。"""

from backend.app.database import DuckDBDatabase
from backend.app.provider import TushareProvider
from backend.app.repository import DailyBasicRepository
from backend.app.services import CNMarketService


def sync_daily_basic(
    lookback_days: int = 3,
) -> int:
    """同步指定自然日范围的市值等每日指标。"""

    database = DuckDBDatabase()
    database.initialize()

    cn_market_service = CNMarketService(
        tushare_provider=TushareProvider(),
        daily_basic_repository=DailyBasicRepository(database),
    )
    return cn_market_service.update_daily_basic(lookback_days)


def main() -> None:
    # 直接运行时显示菜单；API 和定时任务直接调用同步函数。
    print("""
        请选择要执行的任务：

        1. 更新最近 60 日每日指标
        2. 更新近半年每日指标（180 日）
        3. 更新近一年每日指标（365 日）
        4. 更新近三年每日指标（1095 日）
        e. 退出
      """)
    choice = input("请输入选项: ").strip().lower()
    if choice == "e":
        print("退出")
        return
    days = {"1": 60, "2": 180, "3": 365, "4": 1095}.get(choice)
    if days is None:
        print(f"无效选项: {choice}")
        return
    sync_daily_basic(lookback_days=days)


if __name__ == "__main__":
    main()
