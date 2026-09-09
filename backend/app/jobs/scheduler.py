from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.app.config.config import Settings
from backend.app.jobs.tasks import (
    run_daily_k_sync,
    run_stock_daily_basic_sync,
    run_stock_hot_sync,
    run_stock_list_sync,
)


def create_scheduler(settings: Settings) -> BackgroundScheduler:
    """创建 app 应用的定时任务调度器。"""
    scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)

    # 所有定时任务都会使用这些安全设置。
    common = {
        # 如果已经存在相同 id 的任务，就用新任务替换旧任务，避免重复登记。
        "replace_existing": True,
        # 同一个任务最多只允许一个实例运行，避免任务尚未结束又被再次启动。
        "max_instances": 1,
        # 如果程序暂停期间错过了多次执行，只在恢复后补执行一次。
        "coalesce": True,
    }

    """更新股票列表"""
    # 每月更新：每月 1 日 10:00 触发
    scheduler.add_job(
        run_stock_list_sync,
        CronTrigger(
            day=1,
            hour=10,
            minute=0,
            timezone=settings.scheduler_timezone,
        ),
        id="monthly-stock-list-sync",
        **common,
    )

    """更新热门股列表"""
    # 每日更新：周一至周五执行，每天 15:00 触发
    scheduler.add_job(
        run_stock_hot_sync,
        CronTrigger(
            day_of_week="mon-fri",
            hour=15,
            minute=0,
            timezone=settings.scheduler_timezone,
        ),
        id="weekday-stock-hot-sync",
        **common,
    )

    """更新股票日K线列表"""
    # 每日更新：周一到周五，16:00 更新最近 3 日数据。
    scheduler.add_job(
        run_daily_k_sync,
        CronTrigger(
            day_of_week="mon-fri",
            hour=16,
            minute=0,
            timezone=settings.scheduler_timezone,
        ),
        id="weekday-daily-k-sync",
        args=[3, 100],
        **common,
    )

    """更新股票每日指标"""
    # 每日更新：周一至周五执行，每天 16:00 触发
    scheduler.add_job(
        run_stock_daily_basic_sync,
        CronTrigger(
            day_of_week="mon-fri",
            hour=16,
            minute=0,
            timezone=settings.scheduler_timezone,
        ),
        id="weekday-stock-daily-basic-sync",
        **common,
    )

    # 每周校准：每周六 16:00 更新最近 60 日数据。
    scheduler.add_job(
        run_daily_k_sync,
        CronTrigger(
            day_of_week="sat",
            hour=16,
            minute=0,
            timezone=settings.scheduler_timezone,
        ),
        id="weekly-daily-k-sync",
        args=[60, 50],
        **common,
    )

    # 每月校准：每月 1 日 16:00 更新最近 365 日数据。
    scheduler.add_job(
        run_daily_k_sync,
        CronTrigger(
            day=1,
            hour=16,
            minute=0,
            timezone=settings.scheduler_timezone,
        ),
        id="monthly-daily-k-sync",
        args=[365, 10],
        **common,
    )
    return scheduler
