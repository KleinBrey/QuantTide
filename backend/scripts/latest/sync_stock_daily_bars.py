"""日常更新：同步最近 3 个自然日的数据，供历史入口复用同步函数。"""

from backend.app.database import DuckDBDatabase
from backend.app.provider import TushareProvider
from backend.app.repository import DailyBarRepository, StockRepository
from backend.app.services import CNMarketService


def sync_stock_daily_bars(lookback_days: int = 3, batch_size: int = 100) -> None:
    """更新最近指定自然日范围内的日 K 数据。"""
    # 初始化数据库
    database = DuckDBDatabase()
    database.initialize()

    # 注册stock表的repository，用来统一处理增删改查
    stock_repository = StockRepository(database)

    daily_repository = DailyBarRepository(database)

    # 注册API调用

    tushare_provider = TushareProvider()

    # 业务逻辑处理
    cn_market_service = CNMarketService(
        tushare_provider=tushare_provider,
        stock_repository=stock_repository,
        daily_repository=daily_repository,
    )

    cn_market_service.update_daily_bar(lookback_days, batch_size)


def main() -> None:
    sync_stock_daily_bars()


if __name__ == "__main__":
    main()
