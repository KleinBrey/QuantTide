-- 业务数据保存任务配置、分组和成员；股票基础信息、行情仍保留在 DuckDB。
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 100),
    script_id TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(params_json)),
    schedule_json TEXT CHECK (schedule_json IS NULL OR json_valid(schedule_json)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watchlist_groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 100),
    market TEXT CHECK (market IN ('CN', 'HK', 'US')),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (is_default = 0 OR (name = 'stock_pool' AND market IN ('HK', 'US') AND market IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_watchlist_default_market
ON watchlist_groups(market) WHERE is_default = 1;

CREATE TABLE IF NOT EXISTS watchlist_items (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL,
    market TEXT NOT NULL CHECK (market IN ('CN', 'HK', 'US')),
    symbol TEXT NOT NULL CHECK (length(trim(symbol)) BETWEEN 1 AND 32),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (group_id) REFERENCES watchlist_groups(id) ON DELETE CASCADE,
    UNIQUE (group_id, market, symbol)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_items_group ON watchlist_items(group_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_items_stock ON watchlist_items(market, symbol);

CREATE TRIGGER IF NOT EXISTS protect_default_group_delete
BEFORE DELETE ON watchlist_groups WHEN OLD.is_default = 1
BEGIN
    SELECT RAISE(ABORT, '默认 stock_pool 分组不可删除');
END;

CREATE TRIGGER IF NOT EXISTS protect_default_group_update
BEFORE UPDATE OF name, market, is_default ON watchlist_groups WHEN OLD.is_default = 1
BEGIN
    SELECT RAISE(ABORT, '默认 stock_pool 分组不可修改');
END;

CREATE TRIGGER IF NOT EXISTS watchlist_item_market_insert
BEFORE INSERT ON watchlist_items
WHEN EXISTS (SELECT 1 FROM watchlist_groups WHERE id = NEW.group_id
             AND market IS NOT NULL AND market != NEW.market)
BEGIN
    SELECT RAISE(ABORT, '股票市场与分组市场不一致');
END;

CREATE TRIGGER IF NOT EXISTS watchlist_item_market_update
BEFORE UPDATE OF group_id, market ON watchlist_items
WHEN EXISTS (SELECT 1 FROM watchlist_groups WHERE id = NEW.group_id
             AND market IS NOT NULL AND market != NEW.market)
BEGIN
    SELECT RAISE(ABORT, '股票市场与分组市场不一致');
END;
