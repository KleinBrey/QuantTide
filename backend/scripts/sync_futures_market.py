"""期货同步入口；直接运行时先更新合约资料，再同步合约池日 K 线。"""

from backend.app.config.config import get_settings
from backend.app.database import FuturesDuckDBDatabase, SQLiteDatabase
from backend.app.provider import TushareProvider
from backend.app.repository.futures_market_db import FuturesMarketRepository
from backend.app.repository.watchlist import WatchlistRepository
from backend.app.services.futures_market_service import FuturesMarketService


def create_service() -> FuturesMarketService:
    """初始化期货库和自选合约池，创建独立的同步服务。"""
    settings = get_settings()
    database = FuturesDuckDBDatabase(settings.futures_database_path)
    database.initialize()
    app_database = SQLiteDatabase(settings.app_database_path)
    app_database.initialize()
    watchlists = WatchlistRepository(app_database)
    watchlists.ensure_default_pool("FUTURES")
    return FuturesMarketService(
        TushareProvider(), FuturesMarketRepository(database), watchlists
    )


def sync_futures_contracts() -> int:
    """更新主力合约资料及月份映射。"""
    return create_service().update_contracts()


def sync_futures_daily_bars(
    lookback_days: int = 365,
) -> dict[str, int]:
    """仅更新合约池日 K 线；lookback_days 为回溯自然日数。"""
    return create_service().update_daily_bars(lookback_days)


def sync_futures_market(
    lookback_days: int = 365,
) -> dict[str, int]:
    """复用同一服务，先更新主力合约资料，再更新合约池日 K 线。"""
    service = create_service()
    service.update_contracts()
    return service.update_daily_bars(lookback_days)


def main() -> None:
    # 直接运行时显示菜单；API 和定时任务直接调用同步函数。
    print("""
        请选择要执行的任务：

        1. 更新最近 60 日期货日 K 数据
        2. 更新近半年期货日 K 数据（180 日）
        3. 更新近一年期货日 K 数据（365 日）
        4. 更新近三年期货日 K 数据（1095 日）
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
    sync_futures_market(lookback_days=days)


if __name__ == "__main__":
    main()
