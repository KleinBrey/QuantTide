-- 主力合约代码稳定，例如 RB.SHF；不保存为某个到期月份合约。
CREATE TABLE IF NOT EXISTS contracts (
    symbol VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    main_symbol VARCHAR,
    main_name VARCHAR,
    trade_date DATE,
    source VARCHAR NOT NULL DEFAULT 'Tushare',
    update_time TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- volume、open_interest 单位为手，amount 单位为元；价格为未复权主力连续价格。
CREATE TABLE IF NOT EXISTS daily_bars (
    symbol VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    volume DOUBLE, amount DOUBLE, settle DOUBLE, open_interest DOUBLE,
    source VARCHAR NOT NULL DEFAULT 'Tushare',
    update_time TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (symbol, trade_date)
);
