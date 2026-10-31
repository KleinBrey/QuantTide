from pathlib import Path

import duckdb

# 项目根目录：从当前文件所在目录往上四级
PROJECT_ROOT = Path(__file__).resolve().parents[4]

CN_DATABASE_PATH = PROJECT_ROOT / "data" / "cn_market.duckdb"
HK_DATABASE_PATH = PROJECT_ROOT / "data" / "hk_market.duckdb"
US_DATABASE_PATH = PROJECT_ROOT / "data" / "us_market.duckdb"
CRYPTO_DATABASE_PATH = PROJECT_ROOT / "data" / "crypto_market.duckdb"

SCHEMA_DIRECTORY = Path(__file__).parent
CN_SCHEMA_PATH = SCHEMA_DIRECTORY / "cn_schema.sql"
HK_SCHEMA_PATH = SCHEMA_DIRECTORY / "hk_schema.sql"
US_SCHEMA_PATH = SCHEMA_DIRECTORY / "us_schema.sql"
CRYPTO_SCHEMA_PATH = SCHEMA_DIRECTORY / "crypto_schema.sql"


class DuckDBDatabase:

    def __init__(
        self,
        database_path: str | Path = CN_DATABASE_PATH,
        schema_path: str | Path = CN_SCHEMA_PATH,
    ):
        # 把数据库路径转换成完整的绝对路径。
        self.database_path = Path(database_path).expanduser().resolve()
        self.schema_path = Path(schema_path).expanduser().resolve()

    # 初始化duckdb
    def initialize(self) -> None:

        # 如果数据库所在的文件夹不存在，就自动创建它。
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        # 获取初始化SQL脚本
        schema_sql = self.schema_path.read_text(encoding="utf-8")

        # 创建表以后，自动关闭连接。
        with self.connection() as connection:
            connection.execute(schema_sql)

    def connection(self, *, read_only: bool = False):
        # 每次数据库操作都创建一个连接。
        # with 代码块结束时，这个连接会自动关闭。
        connection = duckdb.connect(
            str(self.database_path),
            read_only=read_only,
        )
        return connection


class FuturesDuckDBDatabase(DuckDBDatabase):
    """期货合约和日线使用独立文件。"""

    def __init__(self, database_path=PROJECT_ROOT / "data" / "futures_market.duckdb"):
        super().__init__(database_path, SCHEMA_DIRECTORY / "futures_schema.sql")


class HKDuckDBDatabase(DuckDBDatabase):
    """港股 DuckDB 连接，默认使用独立的港股库和表结构。"""

    def __init__(self, database_path: str | Path = HK_DATABASE_PATH):
        super().__init__(database_path=database_path, schema_path=HK_SCHEMA_PATH)


class USDuckDBDatabase(DuckDBDatabase):
    """美股 DuckDB 连接，默认使用独立的美股库和表结构。"""

    def __init__(self, database_path: str | Path = US_DATABASE_PATH):
        super().__init__(database_path=database_path, schema_path=US_SCHEMA_PATH)


class CryptoDuckDBDatabase(DuckDBDatabase):
    """加密货币独立数据库。"""

    def __init__(self, database_path: str | Path = CRYPTO_DATABASE_PATH):
        super().__init__(database_path=database_path, schema_path=CRYPTO_SCHEMA_PATH)
