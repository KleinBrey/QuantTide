"""同步股票每日指标。"""

from backend.app.database import DuckDBDatabase
from backend.app.provider import TushareProvider
from backend.app.repository import StockDailyBasicRepository
from backend.app.services import Service


def sync_stock_daily_basic() -> int:
    """同步最新交易日的市值等每日指标。"""

    database = DuckDBDatabase()
    database.initialize()

    service = Service(
        tushare_provider=TushareProvider(),
        stock_daily_basic_repository=StockDailyBasicRepository(database),
    )
    return service.update_stock_daily_basic()


def main() -> None:
    sync_stock_daily_basic()


if __name__ == "__main__":
    main()
