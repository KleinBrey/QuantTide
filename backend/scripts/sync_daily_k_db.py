"""同步股票日 K 数据。"""

from backend.app.database import DuckDBDatabase
from backend.app.provider import TushareProvider
from backend.app.repository import DailyBarRepository, StockRepository
from backend.app.services import CNMarketService


def sync_daily_k(lookback_days: int, batch_size: int) -> None:
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

    print("""
            请选择要执行的任务：

            1. 更新最近 3 日数据，每批 100 只
            2. 更新最近 60 日数据，每批 50 只
            3. 更新最近 365 日数据，每批 10 只
            e. 退出
          """)

    choice = input("请输入选项: ").strip()

    match choice:
        case "1":
            sync_daily_k(3, 100)

        case "2":
            sync_daily_k(60, 50)

        case "3":
            sync_daily_k(365, 10)

        case "e":
            print("退出")

        case _:
            print(f"无效选项: {choice}")


if __name__ == "__main__":
    main()
