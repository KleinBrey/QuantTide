"""历史补数：交互式选择最近 60 或 365 个自然日。"""

from backend.scripts.latest.sync_hk_us_daily_bars import sync_hk_us_daily_bars


def main() -> None:
    print("""
            请选择要执行的任务：

            1. 更新港股和美股最近 60 日数据
            2. 更新港股和美股最近 365 日数据
            e. 退出
          """)

    choice = input("请输入选项: ").strip()

    match choice:
        case "1":
            sync_hk_us_daily_bars(60)

        case "2":
            sync_hk_us_daily_bars(365)

        case "e":
            print("退出")

        case _:
            print(f"无效选项: {choice}")


if __name__ == "__main__":
    main()
