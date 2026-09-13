"""同步每日股票热度。"""

from backend.app.config.config import get_settings
from backend.app.database import DuckDBDatabase, HKDuckDBDatabase, USDuckDBDatabase
from backend.app.provider import IwencaiProvider
from backend.app.repository import (
    HKStockHotDailyRepository,
    StockHotDailyRepository,
    USStockHotDailyRepository,
)
from backend.app.services import CNMarketService, HKMarketService, USMarketService


def sync_stock_hot() -> None:
    settings = get_settings()

    # 三个市场分别初始化自己的数据库。
    database = DuckDBDatabase(settings.database_path)
    hk_database = HKDuckDBDatabase(settings.hk_database_path)
    us_database = USDuckDBDatabase(settings.us_database_path)
    database.initialize()
    hk_database.initialize()
    us_database.initialize()

    # 注册股票热度 Repository。
    stock_hot_repository = StockHotDailyRepository(database)
    hk_stock_hot_repository = HKStockHotDailyRepository(hk_database)
    us_stock_hot_repository = USStockHotDailyRepository(us_database)

    # 注册问财 API。
    iwencai_provider = IwencaiProvider()

    # 三个市场分别组装业务服务。
    cn_market_service = CNMarketService(
        iwencai_provider=iwencai_provider,
        stock_hot_repository=stock_hot_repository,
    )
    hk_market_service = HKMarketService(
        iwencai_provider=iwencai_provider,
        stock_hot_repository=hk_stock_hot_repository,
    )
    us_market_service = USMarketService(
        iwencai_provider=iwencai_provider,
        stock_hot_repository=us_stock_hot_repository,
    )

    # 获取并保存当天 A 股、港股和美股热度。
    cn_market_service.update_hot_stock()
    hk_market_service.update_hot_stock()
    us_market_service.update_hot_stock()


def main() -> None:
    sync_stock_hot()


if __name__ == "__main__":
    main()
