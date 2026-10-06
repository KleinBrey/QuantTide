"""日常更新：同步最近 3 个自然日的数据，供历史入口复用同步函数。"""

from backend.app.database import DuckDBDatabase
from backend.app.provider import TushareProvider
from backend.app.repository import DailyBasicRepository
from backend.app.services import CNMarketService


def sync_stock_daily_basic(
    lookback_days: int = 3,
) -> int:
    """同步指定自然日范围的市值等每日指标。"""

    database = DuckDBDatabase()
    database.initialize()

    cn_market_service = CNMarketService(
        tushare_provider=TushareProvider(),
        daily_basic_repository=DailyBasicRepository(database),
    )
    return cn_market_service.update_stock_daily_basic(lookback_days)


def main() -> None:
    sync_stock_daily_basic()


if __name__ == "__main__":
    main()
