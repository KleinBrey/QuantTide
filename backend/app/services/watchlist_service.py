import re

import pandas as pd

from backend.app.repository.watchlist import WatchlistError, WatchlistRepository
from backend.app.utils.symbol import exchange_for, normalize_daily_bar_symbol

MARKET_IDS = {'CN': 'a-share', 'HK': 'hk-share', 'US': 'us-share'}


def normalize_watchlist_symbol(symbol, market):
    value = symbol.strip().upper()
    if market == 'CN':
        if re.fullmatch(r'\d{6}', value):
            value = f'{value}.{exchange_for(value)}'
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', value):
            raise WatchlistError('A 股代码须为六位数字或如 600519.SH')
        return value
    try:
        return normalize_daily_bar_symbol(value, MARKET_IDS[market])
    except ValueError as error:
        raise WatchlistError(str(error)) from error


class WatchlistService:
    def __init__(self, repository: WatchlistRepository, cn_repository, hk_repository, us_repository):
        self.repository = repository
        self.stock_repositories = {'CN': cn_repository, 'HK': hk_repository, 'US': us_repository}

    def _metadata(self, market, symbols=None, query=None, limit=50):
        repository = self.stock_repositories[market]
        table = 'daily_stocks' if market == 'CN' else 'stocks'
        clauses = ['trade_date = (SELECT MAX(trade_date) FROM daily_stocks)'] if market == 'CN' else ['TRUE']
        parameters = []
        if symbols is not None:
            if not symbols:
                return []
            clauses.append(f"symbol IN ({','.join('?' for _ in symbols)})")
            parameters.extend(symbols)
        if query is not None:
            clauses.append('(contains(lower(symbol), lower(?)) OR contains(lower(name), lower(?)))')
            parameters.extend([query, query])
        sql = f"SELECT symbol, name, source, update_time FROM {table} WHERE {' AND '.join(clauses)} ORDER BY symbol"
        if symbols is None:
            sql += ' LIMIT ?'
            parameters.append(limit)
        with repository.db.connection(read_only=True) as connection:
            rows = connection.execute(sql, parameters).df()
        return rows.astype(object).where(pd.notna(rows), None).to_dict(orient='records')

    def search(self, query, market=None, limit=50):
        result = []
        for key in [market] if market else MARKET_IDS:
            rows = self._metadata(key, query=query, limit=limit - len(result))
            result.extend({**row, 'market': key} for row in rows)
            if len(result) >= limit:
                break
        return result

    def list_items(self, group_id):
        items = self.repository.list_items(group_id)
        metadata = {}
        for market in MARKET_IDS:
            symbols = [item['symbol'] for item in items if item['market'] == market]
            metadata.update({(market, row['symbol']): row for row in self._metadata(market, symbols)})
        return [{**item, **metadata.get((item['market'], item['symbol']), {'name': item['symbol'], 'source': None, 'update_time': None})} for item in items]

    def add_item(self, group_id, market, symbol):
        symbol = normalize_watchlist_symbol(symbol, market)
        if not self._metadata(market, [symbol]):
            raise WatchlistError('股票基础信息不存在，请先添加到对应市场股票池', 404)
        return self.repository.add_item(group_id, market, symbol)
