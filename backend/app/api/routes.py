"""汇总各业务模块的 API 路由。"""

from fastapi import APIRouter

from .backtests import router as backtest_router
from .daily_bars import router as daily_bar_router
from .database_sync import router as database_sync_router
from .hot_stocks import router as hot_stock_router
from .signals import router as signal_router
from .stocks import router as stock_router
from .tasks import router as task_router
from .watchlists import router as watchlist_router

router = APIRouter()
router.include_router(watchlist_router)
router.include_router(task_router)
router.include_router(database_sync_router)
router.include_router(stock_router)
router.include_router(hot_stock_router)
router.include_router(daily_bar_router)
router.include_router(signal_router)
router.include_router(backtest_router)
