"""历史补数：交互式选择最近 60 或 365 个自然日。"""

from backend.scripts.latest.sync_stock_daily_bars import sync_stock_daily_bars


def main() -> None:

    print("""
            请选择要执行的任务：

            1. 更新最近 60 日数据，每批 50 只
            2. 更新最近 365 日数据，每批 10 只
            e. 退出
          """)

    choice = input("请输入选项: ").strip()

    match choice:
        case "1":
            sync_stock_daily_bars(60, 50, historical=True)

        case "2":
            sync_stock_daily_bars(365, 10, historical=True)

        case "e":
            print("退出")

        case _:
            print(f"无效选项: {choice}")


if __name__ == "__main__":
    main()
