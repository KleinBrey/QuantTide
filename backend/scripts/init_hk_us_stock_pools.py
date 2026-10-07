"""手动维护港股和美股股票池，修改下方名单后独立运行，不参与自动同步。"""

from __future__ import annotations

import pandas as pd

from backend.app.config.config import get_settings
from backend.app.database import HKDuckDBDatabase, USDuckDBDatabase, SQLiteDatabase
from backend.app.repository.watchlist import WatchlistRepository
from backend.app.repository import HKStockRepository, USStockRepository

# 初始股票池来源
INITIAL_SOURCE = "Initial"

HK_STOCKS = (
    ("00700.HK", "腾讯控股"),
    ("09988.HK", "阿里巴巴-W"),
    ("03690.HK", "美团-W"),
    ("01810.HK", "小米集团-W"),
    ("01024.HK", "快手-W"),
    ("09618.HK", "京东集团-SW"),
    ("09888.HK", "百度集团-SW"),
    ("09999.HK", "网易-S"),
    ("09992.HK", "泡泡玛特"),
    ("00992.HK", "联想集团"),
    ("02513.HK", "智谱"),
    ("00100.HK", "MiniMax"),
    ("00981.HK", "中芯国际"),
    ("01347.HK", "华虹宏力"),
    ("06082.HK", "壁仞科技"),
    ("09903.HK", "天数智芯"),
    ("01888.HK", "建滔积层板"),
    ("03696.HK", "英矽智能"),
    ("02228.HK", "晶泰控股"),
    ("02359.HK", "药明康德"),
    ("03308.HK", "中际旭创"),
    ("02476.HK", "胜宏科技"),
    ("03750.HK", "宁德时代"),
    ("06951.HK", "三环集团"),
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


def init_hk_us_stock_pools(
    hk_database: HKDuckDBDatabase,
    us_database: USDuckDBDatabase,
    app_database: SQLiteDatabase | None = None,
) -> dict[str, int]:
    """幂等写入两个初始股票池，不删除已有的其他股票。"""

    hk_database.initialize()
    us_database.initialize()

    affected = {
        "hk": HKStockRepository(hk_database).upsert_stocks(_stock_frame(HK_STOCKS)),
        "us": USStockRepository(us_database).upsert_stocks(_stock_frame(US_STOCKS)),
    }
    business_db = app_database or SQLiteDatabase(hk_database.database_path.parent / 'app.sqlite')
    business_db.initialize()
    watchlists = WatchlistRepository(business_db)
    watchlists.migrate_stock_pools(
        HKStockRepository(hk_database).get_table_data()['symbol'].tolist(),
        USStockRepository(us_database).get_table_data()['symbol'].tolist(),
    )
    for market, stocks in [('HK', HK_STOCKS), ('US', US_STOCKS)]:
        group_id = watchlists.get_pool(market)['id']
        existing = {row['symbol'] for row in watchlists.list_items(group_id)}
        for symbol, _ in stocks:
            if symbol not in existing:
                watchlists.add_item(group_id, market, symbol)
    return affected


def main() -> None:
    settings = get_settings()
    affected = init_hk_us_stock_pools(
        HKDuckDBDatabase(settings.hk_database_path),
        USDuckDBDatabase(settings.us_database_path),
        SQLiteDatabase(settings.app_database_path),
    )
    print(f"股票池初始化完成：港股 {affected['hk']} 条，美股 {affected['us']} 条")


if __name__ == "__main__":
    main()
