"""任务持久化、API、参数执行和调度生命周期，不请求外部行情。"""

import inspect
import io
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

from apscheduler.events import EVENT_JOB_EXECUTED
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes
from backend.app.api.tasks import router
from backend.app.config.config import Settings
from backend.app.database import SQLiteDatabase
from backend.app.jobs.scheduler import create_scheduler, job_id
from backend.app.jobs.tasks import database_sync_lock
from backend.app.repository.task import TaskRepository
from backend.app.services.task_service import TaskService
from backend.scripts.registry import SCRIPTS


class TaskTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = SQLiteDatabase(Path(temporary.name) / 'app.sqlite')
        self.database.initialize()
        self.repository = TaskRepository(self.database)
        self.settings = Settings(app_database_path=self.database.database_path, scheduler_enabled=False)
        self.scheduler = create_scheduler(self.settings)
        self.service = TaskService(repository=self.repository, scheduler=self.scheduler, settings=self.settings)
        self.service.load_scheduled_tasks()
        self.scheduler.start(paused=True)
        self.addCleanup(lambda: self.scheduler.shutdown(wait=True))
        self.app = FastAPI()
        self.app.state.task_service = self.service
        self.app.include_router(router, prefix='/api')
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def create(self, **overrides):
        body = dict(name='历史日 K', script_id='daily_bars', params={'lookback_days': 60}, schedule=None, enabled=True)
        body.update(overrides)
        response = self.client.post('/api/tasks', json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_registry_all_entries_resolve_without_running(self):
        for script_id, script in SCRIPTS.items():
            with self.subTest(script_id=script_id):
                module, entry = script['run'].split(':')
                function = getattr(import_module(module), entry)
                self.assertTrue(callable(function))
                inspect.signature(function).bind(**script.get('params', {}))

    def test_cli_explicit_lookback_skips_menu(self):
        for script in SCRIPTS.values():
            if 'lookback_days' not in script.get('params', {}):
                continue
            module_name, entry = script['run'].split(':')
            module = import_module(module_name)
            for days in [script['params']['lookback_days'], 180]:
                with (self.subTest(script=entry, days=days), patch.object(module, entry) as sync,
                      patch('builtins.input', side_effect=AssertionError('指定天数时不应显示菜单'))):
                    module.main(['--lookback-days', str(days)])
                    sync.assert_called_once_with(lookback_days=days)

    def test_cli_menu_selects_days_or_exits_without_sync(self):
        for script_id, script in SCRIPTS.items():
            if 'lookback_days' not in script.get('params', {}):
                continue
            module_name, entry = script['run'].split(':')
            module = import_module(module_name)
            choices = [('1', 60), ('2', 365)] if script_id == 'cn_daily_hot' else [
                ('1', 60), ('2', 180), ('3', 365), ('4', 1095),
            ]
            for choice, days in [*choices, ('e', None), ('invalid', None)]:
                with (self.subTest(script=entry, choice=choice), patch.object(module, entry) as sync,
                      patch('builtins.input', return_value=choice), patch('sys.stdout', new_callable=io.StringIO) as output):
                    module.main([])
                    self.assertIn('请选择要执行的任务', output.getvalue())
                    self.assertIn('e. 退出', output.getvalue())
                    if days is None:
                        sync.assert_not_called()
                    else:
                        sync.assert_called_once_with(lookback_days=days)

    def test_tasks_start_empty_and_stay_empty_after_delete_and_restart(self):
        self.assertEqual(self.client.get('/api/tasks').json(), [])
        self.assertEqual(self.scheduler.get_jobs(), [])
        task = self.create(schedule={'trigger': 'cron', 'cron': '0 16 * * mon-fri'})
        self.assertEqual(self.client.delete(f'/api/tasks/{task["id"]}').status_code, 200)
        self.database.initialize()
        self.service.load_scheduled_tasks()
        self.assertEqual(TaskRepository(self.database).list_tasks(), [])
        self.assertEqual(self.scheduler.get_jobs(), [])

    def test_crud_persists_and_updates_scheduler_immediately(self):
        task = self.create(schedule={'trigger': 'cron', 'cron': '0 12 * * mon-fri'})
        task_id = task['id']
        scheduled_id = job_id(task_id)
        self.assertIsNotNone(self.scheduler.get_job(scheduled_id))
        data = dict(name='一年日 K', script_id='daily_bars', params={'lookback_days': 365},
                    schedule={'trigger': 'interval', 'seconds': 3600}, enabled=True)
        response = self.client.put(f'/api/tasks/{task_id}', json=data)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(TaskRepository(self.database).get_task(task_id)['params'], {'lookback_days': 365})
        self.assertEqual(self.scheduler.get_job(scheduled_id).trigger.interval.total_seconds(), 3600)
        self.assertEqual(self.client.patch(f'/api/tasks/{task_id}', json={'enabled': False}).status_code, 200)
        self.assertIsNone(self.scheduler.get_job(scheduled_id))
        self.client.patch(f'/api/tasks/{task_id}', json={'enabled': True})
        self.assertIsNotNone(self.scheduler.get_job(scheduled_id))
        data['schedule'] = None
        self.client.put(f'/api/tasks/{task_id}', json=data)
        self.assertIsNone(self.scheduler.get_job(scheduled_id))
        self.assertEqual(self.client.delete(f'/api/tasks/{task_id}').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/tasks/{task_id}').status_code, 404)
        self.assertEqual(self.client.put('/api/tasks/99999', json=data).status_code, 404)
        self.assertEqual(self.client.post('/api/tasks/99999/run').status_code, 404)

    def test_restart_loads_edited_rules_without_overwriting(self):
        task = self.create(schedule={'trigger': 'cron', 'cron': '30 8 * * sun'}, enabled=False)
        self.database.initialize()
        scheduler = create_scheduler(self.settings)
        fresh = TaskService(repository=TaskRepository(self.database), scheduler=scheduler, settings=self.settings)
        fresh.load_scheduled_tasks()
        self.assertIsNone(scheduler.get_job(job_id(task['id'])))
        self.assertEqual(fresh.repository.get_task(task['id'])['schedule']['cron'], '30 8 * * sun')
        fresh.set_enabled(task['id'], True)
        for name in ['修改一次', '修改两次']:
            fresh.update_task(task['id'], dict(name=name, script_id=task['script_id'],
                                             params=task['params'], schedule=task['schedule'], enabled=True))
        jobs = [job for job in scheduler.get_jobs() if job.id == job_id(task['id'])]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].name, '修改两次')

    def test_retired_pool_script_cannot_be_added(self):
        response = self.client.post('/api/tasks', json={
            'name': '旧股票池初始化', 'script_id': 'init_hk_us_stock_pools',
        })
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.repository.list_tasks(), [])

    def test_table_creation_does_not_depend_on_existing_sqlite_user_version(self):
        legacy = SQLiteDatabase(self.database.database_path.parent / 'legacy.sqlite')
        with sqlite3.connect(legacy.database_path) as connection:
            connection.execute('PRAGMA user_version = 1')
        legacy.initialize()
        self.assertEqual(TaskRepository(legacy).list_tasks(), [])
        with legacy.connection() as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_database_initialization_only_creates_tables(self):
        database = SQLiteDatabase(self.database.database_path.parent / 'empty.sqlite')
        database.initialize()
        self.assertEqual(TaskRepository(database).list_tasks(), [])
        with database.connection() as connection:
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_migrations'"
            ).fetchone())

    def test_scheduler_creation_does_not_load_or_start_tasks(self):
        self.create(schedule={'trigger': 'cron', 'cron': '0 16 * * mon-fri'})
        scheduler = create_scheduler(self.settings)
        service = TaskService(repository=self.repository, scheduler=scheduler, settings=self.settings)
        self.assertEqual(scheduler.get_jobs(), [])
        service.load_scheduled_tasks()
        service.load_scheduled_tasks()
        self.assertEqual(len(scheduler.get_jobs()), 1)
        self.assertFalse(scheduler.running)

    def test_scheduler_triggers_saved_task_and_exposes_next_run(self):
        task = self.create(schedule={'trigger': 'interval', 'seconds': 3600})
        completed = threading.Event()
        self.scheduler.add_listener(lambda event: completed.set(), EVENT_JOB_EXECUTED)
        # 将首次执行设为现在，验证真正的 Scheduler 回调，不等待一小时间隔。
        self.scheduler.modify_job(job_id(task['id']), next_run_time=datetime.now(self.scheduler.timezone))
        with patch('backend.scripts.sync_daily_bars.sync_daily_bars') as sync:
            self.scheduler.resume()
            self.assertTrue(completed.wait(3))
            self.scheduler.pause()
            sync.assert_called_once_with(lookback_days=60)

        row = next(row for row in self.client.get('/api/tasks').json() if row['id'] == task['id'])
        self.assertEqual(row['result']['status'], 'success')
        self.assertTrue(row['next_run_at'].endswith('+08:00'))

    def test_application_startup_assembles_tasks_with_scheduler_enabled_or_disabled(self):
        from backend.app.main import app

        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                settings = self.settings.model_copy(update={
                    'database_path': self.database.database_path.parent / 'cn.duckdb',
                    'hk_database_path': self.database.database_path.parent / 'hk.duckdb',
                    'us_database_path': self.database.database_path.parent / 'us.duckdb',
                    'scheduler_enabled': enabled,
                })
                with patch('backend.app.main.get_settings', return_value=settings), TestClient(app) as client:
                    self.assertIs(app.state.task_service.scheduler, app.state.scheduler)
                    self.assertEqual(app.state.scheduler.running, enabled)
                    self.assertEqual(app.state.scheduler.get_jobs(), [])
                    self.assertEqual(client.get('/api/tasks').json(), [])
                self.assertFalse(app.state.scheduler.running)

    def test_validation_prevents_unknown_scripts_params_and_invalid_schedules(self):
        baseline_count = len(self.repository.list_tasks())
        invalid = [dict(name=' '), dict(script_id='os.system'), dict(params={'unknown': 1}),
                   dict(params={'lookback_days': 0}), dict(params={'lookback_days': True}),
                   dict(params={'lookback_days': '60'}), dict(enabled=None),
                   dict(schedule={}), dict(schedule={'trigger': 'cron', 'cron': 'bad'}),
                   dict(schedule={'trigger': 'cron', 'cron': '0 25 * * *'}),
                   dict(schedule={'trigger': 'cron', 'cron': None}),
                   dict(schedule={'trigger': 'cron', 'cron': '0 16 * * *', 'seconds': 60}),
                   dict(schedule={'trigger': 'unknown'}),
                   dict(schedule={'trigger': 'interval'}),
                   dict(schedule={'trigger': 'interval', 'seconds': 0}),
                   dict(schedule={'trigger': 'interval', 'seconds': '60'}),
                   dict(schedule={'trigger': 'interval', 'seconds': True})]
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                body = dict(name='测试', script_id='daily_bars', params={}, schedule=None, enabled=True)
                body.update(overrides)
                self.assertEqual(self.client.post('/api/tasks', json=body).status_code, 422)
        self.assertEqual(len(self.repository.list_tasks()), baseline_count)
        self.assertEqual(self.create(params={})['params'], {'lookback_days': 3})
        self.assertEqual(len(self.client.get('/api/tasks/scripts').json()['scripts']), 6)

    def test_manual_execution_uses_saved_parameters_and_can_run_when_disabled(self):
        task = self.create(script_id='daily_bars', enabled=False)
        execution_threads = []
        def sync(**kwargs):
            execution_threads.append(threading.get_ident())
        with patch('backend.scripts.sync_daily_bars.sync_daily_bars', side_effect=sync) as function:
            response = self.client.post(f'/api/tasks/{task["id"]}/run')
        self.assertEqual(response.status_code, 200, response.text)
        function.assert_called_once_with(lookback_days=60)
        self.assertNotEqual(execution_threads[0], threading.get_ident())
        self.assertEqual(response.json()['status'], 'success')
        row = next(row for row in self.client.get('/api/tasks').json() if row['id'] == task['id'])
        self.assertEqual(row['result']['status'], 'success')
        self.assertIn('finished_at', row['result'])
        self.assertFalse(database_sync_lock.locked())

    def test_failures_and_partial_failures_release_shared_lock(self):
        task = self.create(script_id='hk_us_daily_bars')
        outcomes = [RuntimeError('接口失败'), {'hk': {'failed_symbols': []}, 'us': {'failed_symbols': ['AAPL']}}]
        for outcome in outcomes:
            with self.subTest(outcome=outcome), patch('backend.scripts.sync_hk_us_daily_bars.sync_hk_us_daily_bars', side_effect=[outcome]):
                response = self.client.post(f'/api/tasks/{task["id"]}/run')
                self.assertEqual(response.status_code, 500)
                self.assertEqual(self.service.results[task['id']]['status'], 'failed')
                self.assertFalse(database_sync_lock.locked())
        self.assertIs(routes.database_sync_lock, database_sync_lock)
        database_sync_lock.acquire()
        try:
            self.assertEqual(self.client.post(f'/api/tasks/{task["id"]}/run').status_code, 409)
        finally:
            database_sync_lock.release()

    def test_running_task_cannot_be_edited_or_deleted_and_scheduled_tasks_wait(self):
        first = self.create(schedule={'trigger': 'interval', 'seconds': 3600})
        second = self.create(schedule={'trigger': 'interval', 'seconds': 3600})
        started, release = threading.Event(), threading.Event()
        def sync(**kwargs):
            started.set()
            self.assertTrue(release.wait(3))
        with ThreadPoolExecutor(max_workers=2) as pool, patch('backend.scripts.sync_daily_bars.sync_daily_bars', side_effect=sync) as function:
            manual = pool.submit(self.service.execute, first['id'])
            self.assertTrue(started.wait(3))
            # 脚本执行期间，列表请求仍能返回当前状态。
            row = next(row for row in self.client.get('/api/tasks').json() if row['id'] == first['id'])
            self.assertEqual(row['result']['status'], 'running')
            self.assertEqual(self.client.delete(f'/api/tasks/{first["id"]}').status_code, 409)
            self.assertEqual(self.client.patch(f'/api/tasks/{first["id"]}', json={'enabled': False}).status_code, 409)
            scheduled = pool.submit(self.service.execute, second['id'], True)
            # 排队中的任务被停用后不再执行。
            self.client.patch(f'/api/tasks/{second["id"]}', json={'enabled': False})
            release.set()
            self.assertEqual(manual.result(timeout=3)['status'], 'success')
            self.assertIsNone(scheduled.result(timeout=3))
            self.assertEqual(function.call_count, 1)


if __name__ == '__main__':
    unittest.main()
