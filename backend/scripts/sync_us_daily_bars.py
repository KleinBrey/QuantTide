"""同步美股日 K 数据；通过 lookback_days 指定自然日范围。"""

from backend.app.config.config import get_settings
from backend.app.database import USDuckDBDatabase, SQLiteDatabase
from backend.app.provider import YFinanceProvider
from backend.app.repository import USDailyBarRepository
from backend.app.repository.watchlist import WatchlistRepository
from backend.app.services import USMarketService


def sync_us_daily_bars(
    lookback_days: int = 3,
    max_workers: int | None = None,
    request_interval: float = 0.5,
    *,
    provider: YFinanceProvider | None = None,
    database: USDuckDBDatabase | None = None,
    app_database: SQLiteDatabase | None = None,
) -> dict[str, int]:
    """初始化依赖并同步美股日 K；同步失败时向调用方抛出异常。"""
    settings = get_settings()
    market_database = database or USDuckDBDatabase(settings.us_database_path)
    market_database.initialize()
    business_database = app_database or SQLiteDatabase(
        market_database.database_path.parent / "app.sqlite"
        if database is not None
        else settings.app_database_path
    )
    business_database.initialize()

    service = USMarketService(
        yfinance_provider=provider if provider is not None else YFinanceProvider(),
        daily_repository=USDailyBarRepository(market_database),
        watchlist_repository=WatchlistRepository(business_database),
    )
    return service.update_daily_bars(
        lookback_days,
        max_workers=(
            max_workers if max_workers is not None else min(settings.sync_workers, lookback_days)
        ),
        request_interval=request_interval,
    )


def main() -> None:
    # 直接运行时显示菜单；API 和定时任务直接调用同步函数。
    print("""
        请选择要执行的任务：

        1. 更新最近 60 日美股日 K 数据
        2. 更新近半年美股日 K 数据（180 日）
        3. 更新近一年美股日 K 数据（365 日）
        4. 更新近三年美股日 K 数据（1095 日）
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
    sync_us_daily_bars(lookback_days=days)


if __name__ == "__main__":
    main()
