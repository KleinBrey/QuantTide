import logging

from backend.scripts.latest.sync_stock_daily_bars import sync_stock_daily_bars
from backend.scripts.latest.sync_hot_stock import sync_hot_stock_latest
from backend.scripts.latest.sync_stock_daily_basic import sync_stock_daily_basic
from backend.scripts.latest.sync_stock_list import sync_stock_list

logger = logging.getLogger(__name__)


def run_stock_list_sync() -> None:
    """执行股票列表同步脚本，并记录未处理的同步异常。"""
    try:
        sync_stock_list()
        logger.info("股票列表同步完成")
    except Exception:
        logger.exception("股票列表同步失败")


def run_stock_hot_sync() -> None:
    """执行热门股同步脚本，并记录未处理的同步异常。"""
    try:
        sync_hot_stock_latest()
        logger.info("热门股同步完成")
    except Exception:
        logger.exception("热门股同步失败")


def run_stock_daily_basic_sync() -> None:
    """执行股票每日指标同步脚本，并记录未处理的同步异常。"""
    try:
        sync_stock_daily_basic()
        logger.info("股票每日指标同步完成")
    except Exception:
        logger.exception("股票每日指标同步失败")


def run_daily_k_sync(lookback_days: int, batch_size: int) -> None:
    """执行指定回看范围的日 K 同步，并记录未处理的同步异常。"""
    try:
        sync_stock_daily_bars(lookback_days, batch_size)
        logger.info("日 K 同步完成: lookback_days=%s", lookback_days)
    except Exception:
        logger.exception("日 K 同步失败: lookback_days=%s", lookback_days)
