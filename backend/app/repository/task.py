"""任务配置的 SQLite 读写，不负责执行脚本或操作调度器。"""

import json

from fastapi import HTTPException

from backend.app.database.sqlite.connection import SQLiteDatabase


class TaskRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

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
            rows = connection.execute('SELECT * FROM tasks ORDER BY sort_order, id')
            return [self.decode(row) for row in rows]

    def get_task(self, task_id: int):
        with self.database.connection() as connection:
            row = connection.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail='任务不存在')
        return self.decode(row)

    def create_task(self, data: dict):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            cursor = connection.execute(
                'INSERT INTO tasks (name, script_id, params_json, schedule_json, enabled, sort_order) '
                'VALUES (?, ?, ?, ?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM tasks))',
                self.values(data),
            )
            task_id = cursor.lastrowid
        return self.get_task(task_id)

    def reorder_tasks(self, ids: list[int]):
        with self.database.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current = {row['id'] for row in connection.execute('SELECT id FROM tasks')}
            if len(ids) != len(set(ids)) or set(ids) != current:
                raise HTTPException(status_code=409, detail='任务列表已变化，排序必须包含全部任务且不能重复，请刷新后重试')
            connection.executemany('UPDATE tasks SET sort_order = ? WHERE id = ?', enumerate(ids))

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
