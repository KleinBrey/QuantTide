"""初始化港股和美股的人工维护股票池。"""

from __future__ import annotations

import pandas as pd

from backend.app.config.config import get_settings
from backend.app.database import HKDuckDBDatabase, USDuckDBDatabase
from backend.app.repository import HKStockRepository, USStockRepository

INITIAL_SOURCE = "Futu"

HK_STOCKS = (
    ("00700.HK", "腾讯控股"),
    ("09988.HK", "阿里巴巴-W"),
    ("03690.HK", "美团-W"),
    ("01810.HK", "小米集团-W"),
    ("00981.HK", "中芯国际"),
    ("01024.HK", "快手-W"),
    ("09618.HK", "京东集团-SW"),
    ("09888.HK", "百度集团-SW"),
    ("09999.HK", "网易-S"),
    ("09992.HK", "泡泡玛特"),
    ("00992.HK", "联想集团"),
    ("02513.HK", "智谱"),
    ("00100.HK", "MiniMax"),
    ("06082.HK", "壁仞科技"),
    ("09903.HK", "天数智芯"),
)

US_STOCKS = (
    ("NVDA", "英伟达"),
    ("AAPL", "苹果"),
    ("MSFT", "微软"),
    ("AMZN", "亚马逊"),
    ("META", "Meta"),
    ("GOOG", "谷歌"),
    ("TSLA", "特斯拉"),
    ("SPCX", "SpaceX"),
    ("AVGO", "博通"),
    ("AMD", "AMD"),
    ("MU", "美光科技"),
    ("INTC", "英特尔"),
    ("ORCL", "甲骨文"),
    ("PLTR", "Palantir"),
    ("MRVL", "Marvell"),
    ("TSM", "台积电 ADR"),
    ("DELL", "戴尔"),
    ("VRT", "Vertiv"),
    ("CRWV", "CoreWeave"),
    ("NBIS", "Nebius"),
    ("HOOD", "Robinhood"),
    ("MSTR", "Strategy"),
    ("COIN", "Coinbase"),
    ("SNDK", "SanDisk"),
)


def _stock_frame(rows: tuple[tuple[str, str], ...]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["symbol", "name"])
    frame["source"] = INITIAL_SOURCE
    return frame


def initialize_hk_us_stocks(
    hk_database: HKDuckDBDatabase,
    us_database: USDuckDBDatabase,
) -> dict[str, int]:
    """幂等写入两个初始股票池，不删除已有的其他股票。"""

    hk_database.initialize()
    us_database.initialize()

    return {
        "hk": HKStockRepository(hk_database).upsert_stocks(_stock_frame(HK_STOCKS)),
        "us": USStockRepository(us_database).upsert_stocks(_stock_frame(US_STOCKS)),
    }


def main() -> None:
    settings = get_settings()
    affected = initialize_hk_us_stocks(
        HKDuckDBDatabase(settings.hk_database_path),
        USDuckDBDatabase(settings.us_database_path),
    )
    print(f"股票池初始化完成：港股 {affected['hk']} 条，" f"美股 {affected['us']} 条")


if __name__ == "__main__":
    main()
