"""Futu OpenD 行情最小连通性测试。"""

from backend.app.provider.futu_provider import FutuProvider


def main() -> None:
    provider = FutuProvider()
    all_count, hot_list = provider.fetch_hot_list(market="US", count=100)

    if hot_list.empty:
        raise RuntimeError("Futu OpenD 热议榜未返回数据")

    display_columns = [
        "security",
        "name",
        "trade_heat",
        "search_heat",
        "news_heat",
        "average_heat",
    ]
    print(f"美股热议榜总数据量：{all_count}")
    print(hot_list[display_columns].to_string(index=False))
    print("\nFutu OpenD smoketest 通过。")


if __name__ == "__main__":
    main()
