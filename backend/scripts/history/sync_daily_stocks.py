"""多线程同步历史股票池；可选近 60 日、近半年、近一年或近三年，每次拉取覆盖已有快照。"""

from backend.scripts.latest.sync_daily_stocks import sync_daily_stocks


def main() -> None:
    print("""
            请选择要执行的任务：

            1. 更新最近 60 日股票池
            2. 更新近半年股票池（180 日）
            3. 更新近一年股票池（365 日）
            4. 更新近三年股票池（1095 日）
            e. 退出
          """)

    choice = input("请输入选项: ").strip()

    match choice:
        case "1":
            sync_daily_stocks(60)

        case "2":
            sync_daily_stocks(180)

        case "3":
            sync_daily_stocks(365)

        case "4":
            sync_daily_stocks(1095)

        case "e":
            print("退出")

        case _:
            print(f"无效选项: {choice}")


if __name__ == "__main__":
    main()
