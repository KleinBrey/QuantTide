"""Futu OpenD 行情最小连通性测试。"""

from backend.app.provider.futu_provider import FutuProvider

from pprint import pprint


def main() -> None:
    provider = FutuProvider()

    # pd = provider.fetch_snapshot(["01191.HK", "AAPL", "TSLA"])

    hot_list = provider.fetch_hot_list(market="US", count=100)

    pprint(hot_list)


if __name__ == "__main__":
    main()
