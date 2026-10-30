"""币安现货行情最小连通性测试。"""

import time
from pprint import pprint

from backend.app.provider import BinanceProvider


def main() -> None:
    provider = BinanceProvider()
    end = int(time.time() * 1000)
    start = end - 7 * 24 * 60 * 60 * 1000
    bars = provider.fetch_historical("BTCUSDT", start, end)
    print(f"共获取 {len(bars)} 条 K 线")
    pprint(bars)
    pprint(provider.fetch_snapshot("BTCUSDT"))
    pprint(provider.fetch_depth("BTCUSDT", limit=5))
    pprint(provider.fetch_trades("BTCUSDT", limit=5))


if __name__ == "__main__":
    main()
