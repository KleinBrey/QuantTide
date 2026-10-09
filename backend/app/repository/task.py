"""任务配置的 SQLite 读写，不负责执行脚本或操作调度器。"""

import json

from fastapi import HTTPException

from backend.app.database.sqlite.connection import SQLiteDatabase


# 每项依次是：任务名称、注册脚本 ID、脚本参数、Cron 规则。
# 保留原页面五个任务，以及原定时器的每周、每月校准任务。
DEFAULT_TASKS = (
    ('股票热度', 'daily_hot', {}, '0 15 * * mon-fri'),
    ('A 股日 K 线数据', 'daily_bars', {'lookback_days': 3}, '0 16 * * mon-fri'),
    ('港美股日 K 线数据', 'hk_us_daily_bars', {'lookback_days': 3}, None),
    ('股票每日指标', 'daily_basic', {'lookback_days': 3}, '0 16 * * mon-fri'),
    ('A 股股票列表', 'daily_stocks', {'lookback_days': 3}, '0 18 * * mon-fri'),
    ('A 股日 K 线每周校准', 'daily_bars', {'lookback_days': 60}, '0 16 * * sat'),
    ('A 股日 K 线每月校准', 'daily_bars', {'lookback_days': 365}, '0 16 1 * *'),
)


class TaskRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def initialize_defaults(self):
        """更新旧脚本引用；默认同步任务仅在首次启动时写入。"""
        with self.database.connection() as connection:
            # 默认任务和初始化标记一起提交，避免同时启动时重复写入。
            connection.execute('BEGIN IMMEDIATE')
            # 股票池改由启动流程创建，旧任务不能再指向已删除的脚本。
            connection.execute("DELETE FROM tasks WHERE script_id = 'init_hk_us_stock_pools'")
            # 合并历史入口，只替换脚本 ID，保留用户的天数、名称和调度规则。
            for script_id in ('daily_bars', 'daily_basic', 'daily_stocks', 'hk_us_daily_bars'):
                connection.execute(
                    'UPDATE tasks SET script_id = ? WHERE script_id = ?',
                    (script_id, f'history_{script_id}'),
                )
            connection.execute(
                "UPDATE tasks SET script_id = 'cn_daily_hot' WHERE script_id = 'history_daily_hot'"
            )
            initialized = connection.execute("SELECT 1 FROM app_migrations WHERE id = 'tasks-v1'").fetchone()
            if initialized:
                return
            if not connection.execute('SELECT 1 FROM tasks LIMIT 1').fetchone():
                for name, script_id, params, cron in DEFAULT_TASKS:
                    schedule = {'trigger': 'cron', 'cron': cron} if cron else None
                    connection.execute(
                        'INSERT INTO tasks (name, script_id, params_json, schedule_json) VALUES (?, ?, ?, ?)',
                        (name, script_id, json.dumps(params), json.dumps(schedule) if schedule else None),
                    )
            # 单独记录“已经初始化”，任务删空后重启也不会重新生成。
            connection.execute("INSERT INTO app_migrations (id) VALUES ('tasks-v1')")

    @staticmethod
    def decode(row):
        # SQLite 保存 JSON 文本，对外返回可直接使用的 Python 字典。
        task = dict(row)
        task['params'] = json.loads(task.pop('params_json'))
        schedule = task.pop('schedule_json')
        task['schedule'] = json.loads(schedule) if schedule else None
        task['enabled'] = bool(task['enabled'])
        return task

    @staticmethod
    def values(data: dict):
        return (
            data['name'],
            data['script_id'],
            json.dumps(data['params'], ensure_ascii=False),
            json.dumps(data['schedule'], ensure_ascii=False) if data['schedule'] else None,
            int(data['enabled']),
        )

    def list_tasks(self):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT * FROM tasks ORDER BY id')
            return [self.decode(row) for row in rows]

    def get_task(self, task_id: int):
        with self.database.connection() as connection:
            row = connection.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail='任务不存在')
        return self.decode(row)

    def create_task(self, data: dict):
        with self.database.connection() as connection:
            cursor = connection.execute(
                'INSERT INTO tasks (name, script_id, params_json, schedule_json, enabled) VALUES (?, ?, ?, ?, ?)',
                self.values(data),
            )
            task_id = cursor.lastrowid
        return self.get_task(task_id)

    def update_task(self, task_id: int, data: dict):
        with self.database.connection() as connection:
            cursor = connection.execute(
                'UPDATE tasks SET name = ?, script_id = ?, params_json = ?, schedule_json = ?, '
                'enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (*self.values(data), task_id),
            )
            if not cursor.rowcount:
                raise HTTPException(status_code=404, detail='任务不存在')
        return self.get_task(task_id)

    def set_enabled(self, task_id: int, enabled: bool):
        with self.database.connection() as connection:
            cursor = connection.execute(
                'UPDATE tasks SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (int(enabled), task_id),
            )
            if not cursor.rowcount:
                raise HTTPException(status_code=404, detail='任务不存在')
        return self.get_task(task_id)

    def delete_task(self, task_id: int):
        with self.database.connection() as connection:
            cursor = connection.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
            if not cursor.rowcount:
                raise HTTPException(status_code=404, detail='任务不存在')
