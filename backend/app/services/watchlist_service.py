import re

import pandas as pd

from backend.app.repository.watchlist import WatchlistError, WatchlistRepository
from backend.app.repository.futures_market_db import MAIN_CONTRACT_FILTER
from backend.app.utils.symbol import exchange_for, normalize_daily_bar_symbol

MARKET_IDS = {"CN": "a-share", "HK": "hk-share", "US": "us-share", "FUTURES": "futures"}


def normalize_watchlist_symbol(symbol, market):
    value = symbol.strip().upper()
    if market == "CRYPTO":
        if not re.fullmatch(r"[A-Z0-9]{2,30}", value):
            raise WatchlistError("交易对代码格式不正确，例如 BTCUSDT")
        return value
    if market == "CN":
        if re.fullmatch(r"\d{6}", value):
            value = f"{value}.{exchange_for(value)}"
        if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", value):
            raise WatchlistError("A 股代码须为六位数字或如 600519.SH")
        return value
    try:
        return normalize_daily_bar_symbol(value, MARKET_IDS[market])
    except ValueError as error:
        raise WatchlistError(str(error)) from error


class WatchlistService:
    def __init__(
        self,
        repository: WatchlistRepository,
        cn_repository,
        hk_repository,
        us_repository,
        crypto_repository=None,
        futures_repository=None,
    ):
        self.repository = repository
        self.stock_repositories = {
            "CN": cn_repository,
            "HK": hk_repository,
            "US": us_repository,
        }
        if futures_repository is not None:
            self.stock_repositories["FUTURES"] = futures_repository
        if crypto_repository is not None:
            self.stock_repositories["CRYPTO"] = crypto_repository

    def _metadata(self, market, symbols=None, query=None, limit=50):
        if symbols == []:
            return []
        repository = self.stock_repositories[market]
        if market == "CRYPTO":
            rows = repository.list_symbols()
            return [
                {**row, "name": row["symbol"], "source": "Binance"}
                for row in rows
                if (symbols is None or row["symbol"] in symbols)
                and (query is None or query.upper() in row["symbol"])
            ][: limit if symbols is None else None]
        table = (
            "daily_stocks"
            if market == "CN"
            else "contracts" if market == "FUTURES" else "stocks"
        )
        clauses = (
            ["trade_date = (SELECT MAX(trade_date) FROM daily_stocks)"]
            if market == "CN"
            else ["TRUE"]
        )
        if market == "FUTURES":
            clauses.append(MAIN_CONTRACT_FILTER)
        parameters = []
        if symbols is not None:
            if not symbols:
                return []
            clauses.append(f"symbol IN ({','.join('?' for _ in symbols)})")
            parameters.extend(symbols)
        if query is not None:
            fields = ["symbol", "name"]
            if market == "FUTURES":
                fields.extend(["main_symbol", "main_name"])
            clauses.append(
                "("
                + " OR ".join(f"contains(lower({field}), lower(?))" for field in fields)
                + ")"
            )
            parameters.extend([query] * len(fields))
        columns = "symbol, name, source, update_time"
        if market == "FUTURES":
            columns = (
                "symbol, COALESCE(main_name, name) AS name, name AS series_name, "
                "main_symbol AS display_symbol, trade_date, source, update_time"
            )
        sql = f"SELECT {columns} FROM {table} WHERE {' AND '.join(clauses)} ORDER BY symbol"
        if symbols is None:
            sql += " LIMIT ?"
            parameters.append(limit)
        with repository.db.connection(read_only=True) as connection:
            rows = connection.execute(sql, parameters).df()
        return rows.astype(object).where(pd.notna(rows), None).to_dict(orient="records")

    def search(self, query, market=None, limit=50):
        result = []
        for key in [market] if market else self.stock_repositories:
            rows = self._metadata(key, query=query, limit=limit - len(result))
            result.extend({**row, "market": key} for row in rows)
            if len(result) >= limit:
                break
        return result

    def list_items(self, group_id):
        items = self.repository.list_items(group_id)
        metadata = {}
        for market in self.stock_repositories:
            symbols = [item["symbol"] for item in items if item["market"] == market]
            metadata.update(
                {
                    (market, row["symbol"]): row
                    for row in self._metadata(market, symbols)
                }
            )
        return [
            {
                **item,
                **metadata.get(
                    (item["market"], item["symbol"]),
                    {"name": item["symbol"], "source": None, "update_time": None},
                ),
            }
            for item in items
        ]

    def reset_futures_pool(self):
        symbols = self.stock_repositories["FUTURES"].list_contract_symbols()
        if not symbols:
            raise WatchlistError(
                "暂无主力合约资料，请先在数据同步中运行“期货市场同步”任务"
            )
        group_id = self.repository.reset_futures_pool(symbols)
        return {"group_id": group_id, "count": len(symbols)}

    def add_item(self, group_id, market, symbol):
        symbol = normalize_watchlist_symbol(symbol, market)
        if market not in self.stock_repositories:
            raise WatchlistError("该市场尚未配置", 422)
        if not self._metadata(market, [symbol]):
            if market == "FUTURES":
                raise WatchlistError("主力合约不存在，请先运行“期货市场同步”任务", 404)
            if market == "CRYPTO":
                raise WatchlistError("交易对行情不存在，请先同步行情", 404)
            raise WatchlistError("股票基础信息不存在，请先添加到对应市场股票池", 404)
        return self.repository.add_item(group_id, market, symbol)
