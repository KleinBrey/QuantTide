"""日常更新：同步最近 3 个自然日的数据，供历史入口复用同步函数。"""

from backend.app.database import DuckDBDatabase
from backend.app.provider import TushareProvider
from backend.app.repository import DailyBarRepository
from backend.app.services import CNMarketService


def sync_daily_bars(lookback_days: int = 3) -> None:
    """更新最近指定自然日范围内的日 K 数据。"""
    # 初始化数据库
    database = DuckDBDatabase()
    database.initialize()

    # 业务逻辑处理
    cn_market_service = CNMarketService(
        tushare_provider=TushareProvider(),
        daily_repository=DailyBarRepository(database),
    )

    cn_market_service.update_daily_bars(lookback_days)


def main() -> None:
    sync_daily_bars()


if __name__ == "__main__":
    main()
