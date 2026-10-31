from __future__ import annotations

import sqlite3

from backend.app.database import SQLiteDatabase


class WatchlistError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class WatchlistRepository:
    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def ensure_default_pool(self, market):
        """应用启动时确保默认股票池存在，保留已有分组和成员。"""
        if market not in {'HK', 'US', 'CRYPTO', 'FUTURES'}:
            raise ValueError('默认池仅支持 HK、US、CRYPTO 和 FUTURES 市场')
        with self.db.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                'SELECT * FROM watchlist_groups WHERE market = ? AND is_default = 1',
                (market,),
            ).fetchone()
            if row is not None:
                return dict(row)
            group_id = connection.execute(
                "INSERT INTO watchlist_groups (name, market, is_default) VALUES ('stock_pool', ?, 1)",
                (market,),
            ).lastrowid
            return self._group(connection, group_id)

    @staticmethod
    def _group(connection, group_id):
        row = connection.execute('SELECT * FROM watchlist_groups WHERE id = ?', (group_id,)).fetchone()
        if row is None:
            raise WatchlistError('自选分组不存在', 404)
        return dict(row)

    def get_group(self, group_id):
        with self.db.connection() as connection:
            return self._group(connection, group_id)

    def get_pool(self, market):
        with self.db.connection() as connection:
            row = connection.execute('SELECT * FROM watchlist_groups WHERE market = ? AND is_default = 1', (market,)).fetchone()
            if row is None:
                raise WatchlistError('该市场没有 stock_pool 分组', 404)
            return dict(row)

    def reset_futures_pool(self, symbols):
        """一次事务替换默认主力合约分组，其他分组不变。"""
        pool = self.get_pool('FUTURES')
        with self.db.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DELETE FROM watchlist_items WHERE group_id = ?', (pool['id'],))
            connection.executemany(
                "INSERT INTO watchlist_items (group_id, market, symbol, sort_order) VALUES (?, 'FUTURES', ?, ?)",
                [(pool['id'], symbol, index) for index, symbol in enumerate(symbols)],
            )
        return pool['id']

    def list_groups(self):
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute('''
                SELECT g.*, COUNT(i.id) AS item_count FROM watchlist_groups g
                LEFT JOIN watchlist_items i ON i.group_id = g.id
                GROUP BY g.id ORDER BY g.sort_order, g.id
            ''')]

    def retain_futures_items(self, symbols):
        """移除已无主力月份映射的期货成员，保留其余成员的 ID 和排序。"""
        if not symbols:
            return 0
        with self.db.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TEMP TABLE valid_futures (symbol TEXT PRIMARY KEY)')
            connection.executemany('INSERT INTO valid_futures VALUES (?)', [(symbol,) for symbol in symbols])
            return connection.execute("""DELETE FROM watchlist_items
                WHERE market = 'FUTURES' AND symbol NOT IN (SELECT symbol FROM valid_futures)""").rowcount

    def create_group(self, name, market=None):
        with self.db.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            group_id = connection.execute('''
                INSERT INTO watchlist_groups (name, market, sort_order)
                VALUES (?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM watchlist_groups))
            ''', (name, market)).lastrowid
            return self._group(connection, group_id)

    def rename_group(self, group_id, name):
        with self.db.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            group = self._group(connection, group_id)
            if group['is_default']:
                raise WatchlistError('默认 stock_pool 分组不可重命名', 409)
            connection.execute('UPDATE watchlist_groups SET name = ? WHERE id = ?', (name, group_id))
            return self._group(connection, group_id)

    def delete_group(self, group_id):
        with self.db.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if self._group(connection, group_id)['is_default']:
                raise WatchlistError('默认 stock_pool 分组不可删除', 409)
            connection.execute('DELETE FROM watchlist_groups WHERE id = ?', (group_id,))

    def list_items(self, group_id):
        with self.db.connection() as connection:
            self._group(connection, group_id)
            return [dict(row) for row in connection.execute(
                'SELECT * FROM watchlist_items WHERE group_id = ? ORDER BY sort_order, id', (group_id,))]

    def add_item(self, group_id, market, symbol):
        with self.db.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            group = self._group(connection, group_id)
            if group['market'] and group['market'] != market:
                raise WatchlistError('股票市场与分组市场不一致')
            try:
                item_id = connection.execute('''
                    INSERT INTO watchlist_items (group_id, market, symbol, sort_order)
                    VALUES (?, ?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM watchlist_items WHERE group_id = ?))
                ''', (group_id, market, symbol, group_id)).lastrowid
            except sqlite3.IntegrityError as error:
                raise WatchlistError('该股票已在分组中', 409) from error
            return dict(connection.execute('SELECT * FROM watchlist_items WHERE id = ?', (item_id,)).fetchone())

    def delete_item(self, group_id, item_id):
        with self.db.connection() as connection:
            self._group(connection, group_id)
            result = connection.execute('DELETE FROM watchlist_items WHERE id = ? AND group_id = ?', (item_id, group_id))
            if not result.rowcount:
                raise WatchlistError('自选条目不存在', 404)

    def remove_stock(self, group_id, market, symbol):
        with self.db.connection() as connection:
            self._group(connection, group_id)
            connection.execute('DELETE FROM watchlist_items WHERE group_id = ? AND market = ? AND symbol = ?', (group_id, market, symbol))

    def reorder(self, ids, group_id=None):
        """整组排序：拒绝缺失、重复或其他分组的 ID，事务内更新。"""
        with self.db.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if group_id is None:
                table = 'watchlist_groups'
                current = {row[0] for row in connection.execute('SELECT id FROM watchlist_groups')}
            else:
                self._group(connection, group_id)
                table = 'watchlist_items'
                current = {row[0] for row in connection.execute('SELECT id FROM watchlist_items WHERE group_id = ?', (group_id,))}
            if len(ids) != len(set(ids)) or set(ids) != current:
                raise WatchlistError('排序必须包含当前列表的全部 ID，且不能重复或包含其他分组的条目', 409)
            connection.executemany(f'UPDATE {table} SET sort_order = ? WHERE id = ?', enumerate(ids))
