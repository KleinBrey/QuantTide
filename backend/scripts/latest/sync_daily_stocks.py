"""日常更新：同步最近 3 个自然日的股票池，供历史脚本、API 和定时任务复用。"""

from backend.app.database import DuckDBDatabase
from backend.app.provider import TushareProvider
from backend.app.repository import DailyStockRepository
from backend.app.services import CNMarketService


def sync_daily_stocks(
    lookback_days: int = 3,
) -> int:
    """按指定自然日范围同步股票池快照。"""

    database = DuckDBDatabase()
    database.initialize()

    service = CNMarketService(
        tushare_provider=TushareProvider(),
        daily_stock_repository=DailyStockRepository(database),
    )
    return service.update_daily_stocks(lookback_days)


def main() -> None:
    sync_daily_stocks()


if __name__ == "__main__":
    main()
