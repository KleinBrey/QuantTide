"""管理任务配置，同步调度，并记录本次服务启动后的执行状态。"""

import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import HTTPException

from backend.app.config.config import Settings
from backend.app.jobs.scheduler import job_id, remove_scheduled_task, sync_scheduled_task
from backend.app.jobs.tasks import database_sync_lock, run_script
from backend.app.repository.task import TaskRepository

logger = logging.getLogger(__name__)


class TaskService:
    def __init__(self, repository: TaskRepository, scheduler: BackgroundScheduler, settings: Settings):
        self.repository = repository
        self.scheduler = scheduler
        self.settings = settings
        self.results = {}
        # 保护配置和执行状态；运行脚本时不持有此锁，页面仍能读取任务列表。
        self.lock = threading.Lock()

    def load_scheduled_tasks(self):
        """应用启动时，将 SQLite 中的任务登记到尚未启动的调度器。"""
        for task in self.repository.list_tasks():
            sync_scheduled_task(self.scheduler, task, self.run_scheduled)

    # 任务配置：读写 SQLite 后，同步更新对应的调度任务。
    def list_tasks(self):
        with self.lock:
            tasks = self.repository.list_tasks()
            for task in tasks:
                task['result'] = self.results.get(task['id'], {'status': 'idle'})
                job = self.scheduler.get_job(job_id(task['id']))
                # 调度器尚未启动时，Job 还没有 next_run_time。
                next_run = getattr(job, 'next_run_time', None)
                task['next_run_at'] = next_run.isoformat() if next_run else None
            return tasks

    def create_task(self, data: dict):
        with self.lock:
            task = self.repository.create_task(data)
            sync_scheduled_task(self.scheduler, task, self.run_scheduled)
            return task

    def reorder_tasks(self, ids: list[int]):
        # 列表顺序不影响执行配置或调度，运行中的任务也可调整位置。
        with self.lock:
            self.repository.reorder_tasks(ids)

    def update_task(self, task_id: int, data: dict):
        with self.lock:
            self.check_not_running(task_id)
            task = self.repository.update_task(task_id, data)
            sync_scheduled_task(self.scheduler, task, self.run_scheduled)
            return task

    def set_enabled(self, task_id: int, enabled: bool):
        with self.lock:
            self.check_not_running(task_id)
            task = self.repository.set_enabled(task_id, enabled)
            sync_scheduled_task(self.scheduler, task, self.run_scheduled)
            return task

    def delete_task(self, task_id: int):
        with self.lock:
            self.check_not_running(task_id)
            self.repository.delete_task(task_id)
            remove_scheduled_task(self.scheduler, task_id)
            self.results.pop(task_id, None)

    def check_not_running(self, task_id: int):
        if self.results.get(task_id, {}).get('status') == 'running':
            raise HTTPException(status_code=409, detail='任务正在执行，完成后再修改或删除')

    # 执行任务：手动运行和定时运行共用 execute()。
    def run_scheduled(self, task_id: int):
        try:
            self.execute(task_id, scheduled=True)
        except HTTPException as error:
            logger.warning('定时任务 %s 未完成：%s', task_id, error.detail)

    def execute(self, task_id: int, scheduled=False):
        # 定时任务等待前一个写入结束；手动任务直接提示“已有任务执行中”。
        if not database_sync_lock.acquire(blocking=scheduled):
            raise HTTPException(status_code=409, detail='已有数据库同步任务正在执行，请稍后再试')
        try:
            with self.lock:
                task = self.repository.get_task(task_id)
                # 排队期间任务可能被停用；拿到写入锁后再读取最新配置。
                if scheduled and (not task['enabled'] or task['schedule'] is None):
                    return None
                self.results[task_id] = {'status': 'running', 'message': '正在执行任务…'}
            # 配置锁已经释放；脚本执行期间，页面仍可查询任务状态。
            started_at = time.perf_counter()
            try:
                run_script(task['script_id'], task['params'])
            except Exception as error:
                result = self.finish(task_id, started_at, 'failed', f"{task['name']}执行失败：{error}")
                logger.exception('任务执行失败: %s', task_id)
                raise HTTPException(status_code=500, detail=result['message']) from error
            return self.finish(task_id, started_at, 'success', f"{task['name']}执行完成")
        finally:
            # 无论成功、失败，还是任务已被停用，都必须释放共享写入锁。
            database_sync_lock.release()

    def finish(self, task_id: int, started_at: float, status: str, message: str):
        result = {
            'status': status,
            'message': message,
            'duration_seconds': round(time.perf_counter() - started_at, 2),
            'finished_at': datetime.now(ZoneInfo(self.settings.scheduler_timezone)).isoformat(timespec='seconds'),
        }
        with self.lock:
            self.results[task_id] = result
        return result
