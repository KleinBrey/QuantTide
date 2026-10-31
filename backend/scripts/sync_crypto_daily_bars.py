"""同步加密货币交易对池日 K 数据；通过 lookback_days 指定自然日范围。"""

from backend.app.config.config import get_settings
from backend.app.database import CryptoDuckDBDatabase, SQLiteDatabase
from backend.app.provider import BinanceProvider
from backend.app.repository.crypto_market_db import CryptoMarketRepository
from backend.app.repository.watchlist import WatchlistRepository
from backend.app.services.crypto_market_service import CryptoMarketService


def sync_crypto_daily_bars(
    lookback_days: int = 3,
    max_workers: int | None = None,
    request_interval: float = 0.5,
    *,
    provider: BinanceProvider | None = None,
    database: CryptoDuckDBDatabase | None = None,
    app_database: SQLiteDatabase | None = None,
) -> dict[str, int]:
    """初始化依赖并同步交易对池日 K；同步失败时向调用方抛出异常。"""
    settings = get_settings()
    market_database = database or CryptoDuckDBDatabase(settings.crypto_database_path)
    market_database.initialize()
    business_database = app_database or SQLiteDatabase(
        market_database.database_path.parent / "app.sqlite"
        if database is not None
        else settings.app_database_path
    )
    business_database.initialize()

    watchlist_repository = WatchlistRepository(business_database)
    watchlist_repository.ensure_default_pool("CRYPTO")
    service = CryptoMarketService(
        provider=provider if provider is not None else BinanceProvider(),
        repository=CryptoMarketRepository(market_database),
        watchlist_repository=watchlist_repository,
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

        1. 更新最近 60 日加密货币日 K 数据
        2. 更新近半年加密货币日 K 数据（180 日）
        3. 更新近一年加密货币日 K 数据（365 日）
        4. 更新近三年加密货币日 K 数据（1095 日）
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
    sync_crypto_daily_bars(lookback_days=days)


if __name__ == "__main__":
    main()
