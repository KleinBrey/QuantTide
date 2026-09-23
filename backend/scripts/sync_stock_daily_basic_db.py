"""同步股票每日指标。"""

from backend.app.database import DuckDBDatabase
from backend.app.provider import TushareProvider
from backend.app.repository import StockDailyBasicRepository
from backend.app.services import CNMarketService


def sync_stock_daily_basic(
    lookback_days: int | None = None,
    max_workers: int = 10,
) -> int:
    """同步指定自然日范围的市值等每日指标。"""

    database = DuckDBDatabase()
    database.initialize()

    cn_market_service = CNMarketService(
        tushare_provider=TushareProvider(),
        stock_daily_basic_repository=StockDailyBasicRepository(database),
    )
    return cn_market_service.update_stock_daily_basic(lookback_days, max_workers)


def main() -> None:
    print("""
            请选择要执行的任务：

            1. 更新最近 3 日数据
            2. 更新最近 60 日数据
            3. 更新最近 365 日数据
            e. 退出
          """)

    choice = input("请输入选项: ").strip()

    match choice:
        case "1":
            sync_stock_daily_basic(3, 100)

        case "2":
            sync_stock_daily_basic(60, 50)

        case "3":
            sync_stock_daily_basic(365, 10)

        case "e":
            print("退出")

        case _:
            print(f"无效选项: {choice}")


if __name__ == "__main__":
    main()
