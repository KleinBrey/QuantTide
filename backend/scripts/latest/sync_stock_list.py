"""同步 A 股股票列表。"""

from backend.app.database import DuckDBDatabase
from backend.app.config.config import get_settings
from backend.app.provider import TushareProvider
from backend.app.repository import DailyStockRepository
from backend.app.services import CNMarketService


def sync_stock_list() -> None:
    # 初始化数据库
    database = DuckDBDatabase(get_settings().database_path)
    database.initialize()

    # 注册stock表的repository，用来统一处理增删改查
    daily_stock_repository = DailyStockRepository(database)

    # 注册API调用
    tushare_provider = TushareProvider()

    # 业务逻辑处理
    cn_market_service = CNMarketService(
        tushare_provider=tushare_provider,
        daily_stock_repository=daily_stock_repository,
    )

    # 插入股票列表数据
    cn_market_service.update_stocks_list()


def main() -> None:
    sync_stock_list()


if __name__ == "__main__":
    main()
