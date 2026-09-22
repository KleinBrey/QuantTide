# 后端说明

后端应用层位于 `backend/app`，纯量化计算引擎位于 `backend/quant`。A 股数据保存到 `data/cn_market.duckdb`，港股与美股分别保存到 `data/hk_market.duckdb` 和 `data/us_market.duckdb`。

## 调用关系

```text
FastAPI / APScheduler / 命令行脚本
                 │
                 ▼
        app（接口、数据与存储）
            │           │
            ▼           ▼
        Provider     Repository ──提供 DataFrame──┐
        外部数据源    DuckDB 读写                  │
            │           │                         ▼
            └───────────┴────────────────── quant（纯量化计算）
                                                 │
                                      因子 → 策略 → 结果
```

## 应用目录

### `app/main.py`

FastAPI 入口，负责初始化数据库、组装 Provider、Repository 和各市场 Service、配置 CORS，以及启动和关闭 APScheduler。

```bash
uv run uvicorn backend.app.main:app \
  --host 127.0.0.1 --port 8001 --reload
```

### `app/api/`

- `routes.py`：股票列表读取和更新接口；
- `dependencies.py`：从 `app.state` 获取共享 Repository 和各市场 Service；
- `GET /api/stocks-list`：读取股票列表；
- `POST /api/stocks-list`：从 Tushare 更新股票列表。
- `GET /api/hot-stock`：读取最新 A 股热度榜；数据更新时间不足 2 小时直接返回，
  否则先从问财同步后返回。
- `GET /api/hk-hot-stock`：读取最新港股热度榜，使用独立的两小时数据库缓存。
- `GET /api/us-hot-stock`：读取最新美股热度榜，使用独立的两小时数据库缓存。
- `GET /api/daily-bars`：通过 `market=a-share|hk-share|us-share` 从对应市场
  DuckDB 查询历史日 K。

### `app/config/`

`config.py` 使用 Pydantic Settings 读取 `backend/.env` 和环境变量，包括 API 前缀、CORS、调度器时区和日 K 更新时间。

### `app/database/`

- `connection.py`：管理 A 股、港股和美股三个 DuckDB 文件的连接；
- `cn_schema.sql`：创建 A 股股票基础信息、日 K、每日指标和热度表；
- `hk_schema.sql`、`us_schema.sql`：分别创建港股与美股的基础信息、日 K 和热度表；
- `operation.sql`、`study.md`：DuckDB 操作和学习记录。

主要表：

- `cn_market.duckdb.stocks`：A 股代码、名称、交易所、市场和来源；
- `hk_market.duckdb.stocks`、`us_market.duckdb.stocks`：对应市场的股票代码、名称和来源；
- `daily_bars`：股票日 K，主键为 `symbol + trade_date`；
- `stock_hot_daily`：问财每日股票热度，主键为 `trade_date + symbol`；
- `hk_market.duckdb.stock_hot_daily`：问财每日港股热度，主键为 `trade_date + symbol`；
- `us_market.duckdb.stock_hot_daily`：问财每日美股热度，主键为 `trade_date + symbol`。

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

Repository 按物理数据库拆分：

- `cn_market_db.py`：A 股股票、日 K、每日指标和热度榜；
- `hk_market_db.py`：港股股票池、日 K 和热度榜；
- `us_market_db.py`：美股股票池、日 K 和热度榜。

Repository 负责字段检查、日期转换以及 DuckDB 的幂等 upsert。

### `app/services/`

- `cn_market_service.py`：负责 A 股股票列表、每日指标、日 K 和热度数据；
- `hk_market_service.py`：负责港股热度数据；
- `us_market_service.py`：负责美股热度数据；
- `hot_stock_service.py`：封装三个市场共用的问财热度格式化和两小时缓存逻辑。

### `app/jobs/`

默认任务：

- 每月 1 日 10:00 更新股票列表；
- 工作日 15:00 更新 A 股、港股和美股热度；
- 工作日配置时间更新最近 3 日的日 K；
- 周六 09:00 校准最近 60 日的日 K；
- 每月 1 日 10:00 校准最近 365 日的日 K。

每个任务设置 `max_instances=1` 和 `coalesce=True`，避免同一任务重复运行。

### `app/utils/` 和 `app/view/`

- `utils/`：日期、交易所和股票代码处理；
- `view/`：Rich 命令行展示示例。

## 量化计算目录

### `quant/factor/`

保存收益率、成交量、动量、波动率和技术指标等纯因子计算。统一入口
`calculate_basic_factors` 只接收 DataFrame，不访问数据库或外部数据源。

### `quant/strategy/`

保存策略注册、结果格式化和具体策略实现。策略计算入口消费股票基础信息、日 K、
市值和热度 DataFrame；每个实现文件的 `__main__` 入口会从 `app` 数据层读取本地数据，
用于独立运行和查看结果。

策略的名称、说明和规则集中配置在 `quant/strategy/strategies.json`。新增策略时，
在该文件增加唯一 `id`，并在 `quant/strategy/registry.py` 的
`STRATEGY_EXECUTORS` 中登记执行函数。

### `quant/stock/`

预留股票池定义和通用股票过滤逻辑，分别放在 `universe.py` 与 `filter.py`。

## 外层同步脚本

```bash
# 股票列表
uv run python -m backend.scripts.sync_stock_list_db

# 初始化港股、美股人工股票池（各 50 只，可重复执行）
uv run python -m backend.scripts.init_hk_us_stock_pools

# 日 K
uv run python -m backend.scripts.sync_daily_k_db
uv run python -m backend.scripts.sync_hk_us_daily_k_db

# 股票热度
uv run python -m backend.scripts.sync_hot_stock_db
```

上述脚本都位于外层 `backend/scripts/`，同步脚本会在写入前自动初始化数据库。

每个策略实现文件都可以单独运行并查看本地结果，例如：

```bash
uv run python -m backend.quant.strategy.implementations.breakout_pullback_n
uv run python -m backend.quant.strategy.implementations.panic_reversal_v
uv run python -m backend.quant.strategy.implementations.recent_volume_breakout
```

六个策略文件分别保留自己的数据读取、Rich 终端展示和 `__main__` 入口。

## 命令入口

- `backend/run.py`：启动 FastAPI；
- `backend/scripts/sync_stock_list_db.py`：同步股票列表；
- `backend/scripts/init_hk_us_stock_pools.py`：幂等初始化港股、美股人工股票池；
- `backend/scripts/sync_daily_k_db.py`：交互式同步日 K，供 `quant-sync` 使用；
- `backend/scripts/sync_hk_us_daily_k_db.py`：通过 Futu OpenD 交互式同步港股和美股日 K；
- `backend/scripts/sync_hot_stock_db.py`：分别向三个市场数据库同步当天股票热度。

```bash
uv run quant-api
uv run quant-sync
```

## 新功能放置位置

| 需求 | 目录 |
| --- | --- |
| 新增外部数据源 | `app/provider/` |
| 修改表结构 | `app/database/cn_schema.sql` |
| 增加数据库读写 | `app/repository/` |
| 增加数据格式化或同步流程 | `app/services/` |
| 增加 HTTP 接口 | `app/api/` 与 `app/schemas/` |
| 增加定时任务 | `app/jobs/` |
| 增加数据同步脚本 | `backend/scripts/` |
| 增加因子 | `quant/factor/` |
| 增加策略 | `quant/strategy/` |
| 增加股票池或通用过滤 | `quant/stock/` |
| 增加测试 | `backend/tests/` |
