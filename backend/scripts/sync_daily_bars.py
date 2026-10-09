"""同步 A 股日 K 数据；通过 lookback_days 指定自然日范围。"""

import argparse

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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="同步 A 股日 K 数据")
    parser.add_argument("--lookback-days", type=int, help="同步最近多少个自然日（含今天）")
    args = parser.parse_args(argv)
    days = args.lookback_days
    # 不传命令行参数时显示菜单；API 和定时任务直接调用同步函数。
    if days is None:
        print("""
            请选择要执行的任务：

            1. 更新最近 60 日日 K 数据
            2. 更新近半年日 K 数据（180 日）
            3. 更新近一年日 K 数据（365 日）
            4. 更新近三年日 K 数据（1095 日）
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
    sync_daily_bars(lookback_days=days)


if __name__ == "__main__":
    main()
