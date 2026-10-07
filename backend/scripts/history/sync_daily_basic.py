"""历史补数：交互式选择最近 60、180、365 或 1095 个自然日。"""

from backend.scripts.latest.sync_daily_basic import sync_daily_basic


def main() -> None:
    print("""
            请选择要执行的任务：

            1. 更新最近 60 日每日指标
            2. 更新近半年每日指标（180 日）
            3. 更新近一年每日指标（365 日）
            4. 更新近三年每日指标（1095 日）
            e. 退出
          """)

    choice = input("请输入选项: ").strip()

    match choice:
        case "1":
            sync_daily_basic(60)

        case "2":
            sync_daily_basic(180)

        case "3":
            sync_daily_basic(365)

        case "4":
            sync_daily_basic(1095)

        case "e":
            print("退出")

        case _:
            print(f"无效选项: {choice}")


if __name__ == "__main__":
    main()
