"""
==================================================
知识点：DuckDB 连接数据库和 CRUD（增、查、改、删）
==================================================

DuckDB 是面向分析的嵌入式数据库，擅长列式分析和直接查询 CSV/Parquet。
先安装：python -m pip install duckdb
"""

# 尝试导入第三方库。没有安装时，给出安装提示，而不是直接报错退出。
try:
    import duckdb
except ImportError:
    print("缺少 duckdb，请运行：python -m pip install duckdb")
else:
    # :memory: 表示创建内存数据库。
    # 数据只存在于程序运行期间，程序结束后会自动消失。
    # 如果需要保存到硬盘，可以改成 duckdb.connect("cn_market.duckdb")。
    connection = duckdb.connect(database=":memory:")

    try:
        # 1. 建表
        # PRIMARY KEY 表示 symbol 和 trade_date 的组合不能重复。
        connection.execute(
            """
            CREATE TABLE prices (
                symbol VARCHAR,
                trade_date DATE,
                close DOUBLE,
                PRIMARY KEY (symbol, trade_date)
            )
            """
        )

        # 2. 增加数据（Create）
        # executemany 可以使用同一条 SQL 一次插入多行数据。
        # SQL 中的 ? 是参数占位符，会依次使用元组中的值。
        connection.executemany(
            """
            INSERT INTO prices (symbol, trade_date, close)
            VALUES (?, ?, ?)
            """,
            [
                ("600519", "2026-08-13", 1680.0),
                ("600519", "2026-08-14", 1688.0),
                ("000001", "2026-08-14", 10.5),
            ],
        )

        # 3. 查询数据（Read）
        # 查询价格高于 100 元的数据，并按价格从高到低排列。
        rows = connection.execute(
            """
            SELECT symbol, trade_date, close
            FROM prices
            WHERE close > ?
            ORDER BY close DESC
            """,
            [100],
        ).fetchall()

        # fetchall() 把查询结果取出，返回由多个元组组成的列表。
        print("价格高于 100 元：", rows)

        # 4. 修改数据（Update）
        # 把贵州茅台在指定日期的收盘价改成 1690。
        connection.execute(
            """
            UPDATE prices
            SET close = ?
            WHERE symbol = ? AND trade_date = ?
            """,
            [1690.0, "600519", "2026-08-14"],
        )

        updated_row = connection.execute(
            """
            SELECT symbol, trade_date, close
            FROM prices
            WHERE symbol = ? AND trade_date = ?
            """,
            ["600519", "2026-08-14"],
        ).fetchone()
        print("修改后的数据：", updated_row)

        # 5. 删除数据（Delete）
        # 删除平安银行在指定日期的数据。
        connection.execute(
            """
            DELETE FROM prices
            WHERE symbol = ? AND trade_date = ?
            """,
            ["000001", "2026-08-14"],
        )

        remaining_rows = connection.execute(
            """
            SELECT symbol, trade_date, close
            FROM prices
            ORDER BY symbol, trade_date
            """
        ).fetchall()
        print("删除后的全部数据：", remaining_rows)

    finally:
        # 无论上面的代码是否报错，最终都会关闭数据库连接。
        connection.close()

"""
本节总结：先连接数据库，再通过 INSERT、SELECT、UPDATE、DELETE 完成增删改查。
"""
