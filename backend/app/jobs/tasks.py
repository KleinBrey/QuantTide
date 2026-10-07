import logging

from backend.scripts.latest.sync_daily_bars import sync_daily_bars
from backend.scripts.latest.sync_daily_hot import sync_daily_hot
from backend.scripts.latest.sync_daily_basic import sync_daily_basic
from backend.scripts.latest.sync_daily_stocks import sync_daily_stocks

logger = logging.getLogger(__name__)


def run_daily_stocks_sync() -> None:
    """执行股票列表同步脚本，并记录未处理的同步异常。"""
    try:
        sync_daily_stocks()
        logger.info("股票列表同步完成")
    except Exception:
        logger.exception("股票列表同步失败")


def run_daily_hot_sync() -> None:
    """执行热门股同步脚本，并记录未处理的同步异常。"""
    try:
        sync_daily_hot()
        logger.info("热门股同步完成")
    except Exception:
        logger.exception("热门股同步失败")


def run_daily_basic_sync() -> None:
    """执行股票每日指标同步脚本，并记录未处理的同步异常。"""
    try:
        sync_daily_basic()
        logger.info("股票每日指标同步完成")
    except Exception:
        logger.exception("股票每日指标同步失败")


def run_daily_bars_sync(lookback_days: int) -> None:
    """执行指定回看范围的日 K 同步，并记录未处理的同步异常。"""
    try:
        sync_daily_bars(lookback_days)
        logger.info("日 K 同步完成: lookback_days=%s", lookback_days)
    except Exception:
        logger.exception("日 K 同步失败: lookback_days=%s", lookback_days)
