# 后端说明

后端主应用统一位于 `backend/app`，运行数据统一保存到项目根目录的 `data/market.duckdb`。

## 调用关系

```text
FastAPI / APScheduler / 命令行脚本
                 │
                 ▼
              Service
          数据格式化与同步编排
            │           │
            ▼           ▼
        Provider     Repository
        外部数据源    DuckDB 读写
                          │
                          ▼
                  data/market.duckdb
```

## 应用目录

### `app/main.py`

FastAPI 入口，负责初始化数据库、组装 Provider、Repository 和 Service、配置 CORS，以及启动和关闭 APScheduler。

```bash
uv run uvicorn backend.app.main:app \
  --host 127.0.0.1 --port 8001 --reload
```

### `app/api/`

- `routes.py`：股票列表读取和更新接口；
- `dependencies.py`：从 `app.state` 获取共享 Repository 和 Service；
- `GET /api/stocks-list`：读取股票列表；
- `POST /api/stocks-list`：从 Tushare 更新股票列表。
- `GET /api/hot-stock`：读取最新 A 股热度榜；数据更新时间不足 2 小时直接返回，
  否则先从问财同步后返回。
- `GET /api/hk-hot-stock`：读取最新港股热度榜，使用独立的两小时数据库缓存。
- `GET /api/us-hot-stock`：读取最新美股热度榜，使用独立的两小时数据库缓存。

### `app/config/`

`config.py` 使用 Pydantic Settings 读取 `backend/.env` 和环境变量，包括 API 前缀、CORS、调度器时区和日 K 更新时间。

### `app/database/`

- `connection.py`：管理 `data/market.duckdb` 的普通连接和 DuckDB Web UI 长连接；
- `schema.sql`：创建股票基础信息、日 K 以及 A 股、港股、美股热度表；
- `operation.sql`、`study.md`：DuckDB 操作和学习记录。

主要表：

- `stocks`：股票代码、名称、交易所、市场、类型和来源；
- `daily_bars`：股票日 K，主键为 `symbol + date`；
- `stock_hot_daily`：问财每日股票热度，主键为 `trade_date + symbol`；
- `hk_stock_hot_daily`：问财每日港股热度，主键为 `trade_date + symbol`；
- `us_stock_hot_daily`：问财每日美股热度，主键为 `trade_date + symbol`。

### `app/provider/`

- `tushare_provider.py`：股票列表、日 K、复权行情和每日市值指标；
- `hithink_provider.py`：HiThink 股票列表、快照和历史行情；
- `akshare_provider.py`：AkShare 股票列表和历史行情适配；
- `futu_provider.py`：通过本机 Futu OpenD 获取股票列表、快照、历史 K 线和热议榜；
- `iwencai_provider.py`：问财股票热度查询；
- `example/`：各 Provider 的手动冒烟测试。

Futu OpenD 登录并监听本机 `11111` 端口后，可运行美股热议榜冒烟测试：

```bash
uv run python -m backend.app.provider.example.futu_smoke_test
```

### `app/repository/`

`duck_db.py` 按表拆分数据访问：

- `StockRepository`；
- `DailyBarRepository`；
- `StockHotDailyRepository`；
- `HKStockHotDailyRepository`；
- `USStockHotDailyRepository`。

Repository 负责字段检查、日期转换以及 DuckDB 的幂等 upsert。

### `app/services/`

`market_data.py` 中的 `Service` 负责：

- 统一股票列表字段并保存；
- 统一 Tushare、HiThink 日 K 字段并保存；
- 批量并发同步股票日 K；
- 格式化并保存问财股票热度。

### `app/jobs/`

默认任务：

- 每月 1 日 10:00 更新股票列表；
- 工作日 15:00 更新 A 股、港股和美股热度；
- 工作日配置时间更新最近 3 日的日 K；
- 周六 09:00 校准最近 60 日的日 K；
- 每月 1 日 10:00 校准最近 365 日的日 K。

每个任务设置 `max_instances=1` 和 `coalesce=True`，避免同一任务重复运行。

### `app/strategy/`

包含股票热度与量价突破策略，使用股票基础信息、日 K、每日市值和问财热度进行筛选。

策略的名称、说明和规则集中配置在 `app/strategy/strategies.json`。新增策略时，
在该文件增加一个唯一的 `id`，并在 `app/strategy/registry.py` 的
`STRATEGY_EXECUTORS` 中登记对应执行函数。

### `app/utils/` 和 `app/view/`

- `utils/`：日期、交易所和股票代码处理；
- `view/`：Rich 命令行展示示例。

## 外层同步脚本

```bash
# 股票列表
uv run python -m backend.scripts.sync_stock_list_db

# 日 K
uv run python -m backend.scripts.sync_daily_k_db

# 股票热度
uv run python -m backend.scripts.sync_stock_hot_db
```

三个脚本都位于外层 `backend/scripts/`，并会在同步前自动初始化数据库。

## 命令入口

- `backend/run.py`：启动 FastAPI；
- `backend/scripts/sync_stock_list_db.py`：同步股票列表；
- `backend/scripts/sync_daily_k_db.py`：交互式同步日 K，供 `quant-sync` 使用；
- `backend/scripts/sync_stock_hot_db.py`：同步当天股票热度。

```bash
uv run quant-api
uv run quant-sync
```

## 新功能放置位置

| 需求 | 目录 |
| --- | --- |
| 新增外部数据源 | `app/provider/` |
| 修改表结构 | `app/database/schema.sql` |
| 增加数据库读写 | `app/repository/` |
| 增加数据格式化或同步流程 | `app/services/` |
| 增加 HTTP 接口 | `app/api/` 与 `app/schemas/` |
| 增加定时任务 | `app/jobs/` |
| 增加数据同步脚本 | `backend/scripts/` |
| 增加策略 | `app/strategy/` |
| 增加测试 | `backend/tests/` |
