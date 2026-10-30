-- 币安现货日 K；日期按 UTC 划分，成交量为基础币数量，成交额为计价币金额。
CREATE TABLE IF NOT EXISTS daily_bars (
    symbol VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume DOUBLE NOT NULL CHECK (volume >= 0),
    amount DOUBLE NOT NULL,
    source VARCHAR NOT NULL,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, trade_date),
    CHECK (high >= greatest(open, low, close)),
    CHECK (low <= least(open, high, close))
);
