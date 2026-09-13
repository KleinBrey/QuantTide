-- 股票基础信息表：每只股票保存一条记录。
CREATE TABLE IF NOT EXISTS stocks (
  symbol VARCHAR NOT NULL PRIMARY KEY,
  name VARCHAR NOT NULL,
  source VARCHAR NOT NULL,
  -- 记录更新时间；插入时未指定则使用数据库当前时间。
  update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 股票历史日线数据：保存股票在每个交易日的行情数据。
CREATE TABLE IF NOT EXISTS daily_bars (
  -- 股票代码。
  symbol VARCHAR NOT NULL,
  -- 交易日期。
  trade_date DATE NOT NULL,
  -- 开盘价。
  open DOUBLE NOT NULL,
  -- 最高价。
  high DOUBLE NOT NULL,
  -- 最低价。
  low DOUBLE NOT NULL,
  -- 收盘价。
  close DOUBLE NOT NULL,
  -- 成交量，不允许为负数。 
  volume DOUBLE NOT NULL,
  -- 成交额。
  amount DOUBLE,
  -- 该条行情数据的来源。
  source VARCHAR NOT NULL,
  -- 记录更新时间；插入时未指定则使用数据库当前时间。
  update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- 同一股票、同一交易日只能存在一条记录。
  PRIMARY KEY (symbol, trade_date),
  -- 最高价必须不低于开盘价、最高价、最低价和收盘价中的任意值。
  CHECK (high >= greatest(open, high, low, close)),
  -- 最低价必须不高于开盘价、最高价、最低价和收盘价中的任意值。
  CHECK (low <= least(open, high, low, close)),
  -- 成交量不能为负数。
  CHECK (volume >= 0)
);


-- 港股每日热度榜。
CREATE TABLE IF NOT EXISTS stock_hot_daily (
  trade_date DATE NOT NULL,
  symbol VARCHAR NOT NULL,
  name VARCHAR NOT NULL,
  price DOUBLE,
  change_pct DOUBLE,
  hot_value DOUBLE NOT NULL,
  source VARCHAR NOT NULL DEFAULT 'Iwencai',
  update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (trade_date, symbol)
);
