from contextlib import contextmanager
from pathlib import Path
import sqlite3

from .connection import PROJECT_ROOT, SCHEMA_DIRECTORY


class SQLiteDatabase:
    def __init__(self, database_path: str | Path = PROJECT_ROOT / 'data' / 'app.sqlite'):
        self.database_path = Path(database_path).expanduser().resolve()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute('PRAGMA journal_mode = WAL')
            connection.executescript((SCHEMA_DIRECTORY / 'app_schema.sql').read_text(encoding='utf-8'))
