"""股票通用过滤逻辑。"""

import pandas as pd


def merge_stock_basic(
    stocks: pd.DataFrame,
    stock_daily_basic: pd.DataFrame,
) -> pd.DataFrame:
    """补齐股票市值动态字段。"""

    # 股票主表不含动态市值，因此按 symbol 从每日基础指标表补齐。
    return stocks.merge(stock_daily_basic, on="symbol", how="left")


def filter_stocks_basic(min_market_cap: float, stocks: pd.DataFrame) -> pd.DataFrame:
    """排除 ST、科创板和北交所股票。"""

    return filter_market_cap(min_market_cap, filter_static_stocks(stocks))


def filter_static_stocks(stocks: pd.DataFrame) -> pd.DataFrame:
    """过滤不依赖交易日期的股票属性。"""

    # 分别保留布尔条件，便于以后单独调整某项股票池规则。
    is_st = stocks["name"].str.contains("ST", na=False)
    is_star_market = stocks["market"] == "科创板"
    is_beijing = stocks["exchange"] == "BJ"
    return stocks.loc[~is_st & ~is_star_market & ~is_beijing]


def filter_market_cap(min_market_cap: float, stocks: pd.DataFrame) -> pd.DataFrame:
    """使用已按时点匹配的市值过滤股票。"""

    result = stocks
    result["market_cap"] = pd.to_numeric(result["market_cap"], errors="coerce")
    return result[result["market_cap"] > min_market_cap]


def filter_stocks(
    min_market_cap: float,
    stocks: pd.DataFrame,
    stock_daily_basic: pd.DataFrame,
) -> pd.DataFrame:
    """过滤股票池，排除 ST、科创板和北交所股票，并按市值过滤。"""

    stocks = merge_stock_basic(stocks, stock_daily_basic)
    return filter_stocks_basic(min_market_cap, stocks)
