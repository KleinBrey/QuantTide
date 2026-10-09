"""调度器的创建和任务登记；不读数据库，也不启动调度器。"""

from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.app.config.config import Settings


def create_scheduler(settings: Settings) -> BackgroundScheduler:
    return BackgroundScheduler(timezone=settings.scheduler_timezone)


def job_id(task_id: int) -> str:
    return f'task-{task_id}'


def remove_scheduled_task(scheduler: BackgroundScheduler, task_id: int) -> None:
    if scheduler.get_job(job_id(task_id)) is not None:
        scheduler.remove_job(job_id(task_id))


def sync_scheduled_task(scheduler: BackgroundScheduler, task: dict, run_task: Callable) -> None:
    """让内存中的调度与已保存的任务配置一致。"""
    # 先移除旧任务：停用、改成手动运行或启动前反复编辑，都不会留下旧配置。
    remove_scheduled_task(scheduler, task['id'])
    if not task['enabled'] or task['schedule'] is None:
        return

    schedule = task['schedule']
    if schedule['trigger'] == 'cron':
        trigger = CronTrigger.from_crontab(schedule['cron'], timezone=scheduler.timezone)
    else:
        trigger = IntervalTrigger(seconds=schedule['seconds'], timezone=scheduler.timezone)

    scheduler.add_job(
        run_task,
        trigger=trigger,
        id=job_id(task['id']),
        name=task['name'],
        args=[task['id']],  # 执行时按 ID 读取最新配置，不在调度器里保存另一份配置。
        max_instances=1,  # 同一任务的上一次执行未完成时，不再启动下一次。
        coalesce=True,  # 错过的多次触发合并成一次。
    )
