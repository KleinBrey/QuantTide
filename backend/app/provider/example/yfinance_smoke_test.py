"""Yahoo Finance 港股、美股历史日 K 最小连通性测试。"""

import time

import pandas as pd

from backend.app.provider.yfinance_provider import YFinanceProvider


def main() -> None:
    provider = YFinanceProvider()
    end = int(time.time() * 1000)
    start = end - 30 * 24 * 60 * 60 * 1000

    print(f"正在获取 AAPL 最近 30 日的日 K")

    data = provider.fetch_historical(
        thscode="AAPL",
        start=start,
        end=end,
        interval="1d",
        adjust="forward",
    )["data"]["item"]

    frame = pd.DataFrame(data)

    print(f"共返回 {len(frame)} 条结果，以下展示前 20 条：\n{frame.head(20)}")


if __name__ == "__main__":
    main()
