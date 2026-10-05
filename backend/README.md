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
                         因子计算 → 形态信号 → 交易策略 → 回测评估
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

三个市场的热度表统一存储 `rank INTEGER`（正整数，1 为热度最高），接口也返回 `rank`，查询按排名升序排列。问财快照按热度值降序生成排名，A 股历史补齐使用 HiThink 返回的原始排名。策略输出中的 `hot_rank` 直接取自该排名，不再按结果行号重新编号。

热榜同步要求传入完整榜单；在同一事务内删除输入交易日的旧榜单并插入新榜单，失败则回滚，其他日期不受影响。空榜或清洗丢失记录时拒绝更新。新建表保留 `(trade_date, symbol)` 主键，并增加 `(trade_date, rank)` 唯一约束；已有表不会因 `CREATE TABLE IF NOT EXISTS` 自动增加约束，现有表由股票主键和写入前的排名检查防止重复。

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

职责仅限因子计算。保存收益率、成交量、动量、波动率和技术指标等纯计算。统一入口
`calculate_basic_factors` 只接收 DataFrame，不访问数据库或外部数据源。

### `quant/signal/`

职责仅限形态识别与选股信号。保存信号实现、注册、展示配置和接口结果格式化。
`patterns/` 下的每个文件
负责识别一种信号形态，计算入口消费股票基础信息、日 K、市值和热度 DataFrame；
文件的 `__main__` 入口会从 `app` 数据层读取本地数据，用于独立运行和查看结果。
信号层不决定买入、卖出、止损或止盈。

信号的名称、说明和规则集中配置在 `quant/signal/signals.json`。新增信号时，在该文件
增加唯一 `id`，并在 `quant/signal/registry.py` 的 `SIGNAL_EXECUTORS` 中关联对应的
`patterns/` 执行函数。

### `quant/strategy/`

职责仅限买卖规则与交易策略。当前 `today_confirmed_breakout.py` 提供
`TodayConfirmedBreakoutStrategy`：它组合 `TodayConfirmedBreakoutPattern` 的识别结果，
生成入场、止损和止盈价格，并统一提供退出规则；本层不负责账户撮合或绩效计算。

### `quant/stock/`

预留股票池定义和通用股票过滤逻辑，分别放在 `universe.py` 与 `filter.py`。

### `quant/backtest/`

职责仅限模拟执行与绩效评估。`BacktestEngine(strategy, config)` 接收策略实例，
负责交易日循环、先卖后买、仓位上限、整手成交、费用和每日估值。
`account.py`、`position.py` 负责账户和持仓，`result.py` 计算绩效。
买卖条件、信号排序以及止盈止损价格由策略决定，引擎不读取某个策略的配置。

默认策略为注册表中的第一个。命令行入口使用最近 12 个月、100 万初始资金、
最多 20 只股票、单只建仓上限 5%：

```bash
uv run quant-backtest
```

前端通过 `GET /api/backtests/strategies` 获取策略列表，默认选中第一个策略。
页面默认最近 6 个月，调整参数后点击“执行回测”运行。
执行回测使用 `GET /api/backtests/{strategy_id}`，支持 `start_date`、`end_date`、
`lookback_months`、`max_positions`、`max_position_pct` 和 `initial_cash` 参数。
每次请求创建独立策略实例和账户；不同策略分别回测，不共用资金。

### 添加一个回测策略

1. 在 `quant/strategy/` 新建策略类，提供 `id`、`name`、`description`。
2. 实现 `generate_entries_range(...)`、`find_exits(...)`、`assumptions()`，
   接口见 `quant/strategy/base.py`。不需要继承基类。
3. 在 `quant/strategy/registry.py` 的 `STRATEGIES` 中登记该类。
   重启后端后，前端下拉框会自动显示，无需修改引擎或页面。

入场结果为 DataFrame，包含 `symbol`、`name`、`entry_date`、`signal_date`、
`selection_rank`、`entry_reason`；排名数值越小，买入优先级越高。
日期使用归一化的 pandas Timestamp，同一股票同一天最多一条候选。
`stop_loss_price`、`take_profit_price` 可选，仅用于记录和展示；
引擎不会自动执行止盈止损，策略需在 `find_exits` 中处理。

退出结果包含 `symbol`、`entry_date`、`exit_date`、`exit_reason`，
每个候选至多一个退出日，且必须晚于入场日并有当日行情。
没有退出信号时返回带列名的空 DataFrame，仓位保留到回测结束。
`assumptions()` 返回策略说明列表，可以为空。

策略批量计算候选入场和对应退出日期，引擎只执行实际买入的候选。
入场信号不能使用入场日之后的数据；退出条件不能使用退出日之后的数据。
这种方式适合当前按日、整仓买卖的策略，不包含加减仓或共享账户的多策略组合。

当前正式策略只有“放量突破次日确认”。选股信号只有补齐入场、退出规则后，
才应注册为可回测策略。测试中的持有一天和持有至期末策略仅验证引擎通用性。

## 外层同步脚本

```bash
# 股票列表
uv run python -m backend.scripts.latest.sync_stock_list

# 更新港股、美股人工股票池（可重复执行）
uv run python -m backend.scripts.latest.sync_hk_us_stock_pools

# 最近 3 个自然日的每日指标和日 K
uv run python -m backend.scripts.latest.sync_stock_daily_basic
uv run python -m backend.scripts.latest.sync_stock_daily_bars
uv run python -m backend.scripts.latest.sync_hk_us_daily_bars

# 股票热度
uv run python -m backend.scripts.latest.sync_hot_stock
```

日常更新入口位于 `backend/scripts/latest/`，直接执行，不再弹出日期选择菜单。
日 K 和每日指标默认更新最近 3 个自然日；股票热度同步当天数据；股票列表和
股票池更新基础资料。同步脚本会在写入前自动初始化数据库。

历史补数入口位于 `backend/scripts/history/`。每日指标和日 K 可交互式选择
最近 60 或 365 个自然日，与日常入口共用同步函数；A 股日 K 分别每批 50、10 只：

```bash
uv run python -m backend.scripts.history.sync_stock_daily_basic
uv run python -m backend.scripts.history.sync_stock_daily_bars
uv run python -m backend.scripts.history.sync_hk_us_daily_bars
```

补齐 A 股股票池历史热度排名，运行后可选择最近 60 或 365 个自然日（含今天）：

```bash
uv run python -m backend.scripts.history.sync_hot_stock
```

读取 A 股库 `stocks` 中的全部股票，每只股票调用一次 HiThink 个股排名走势接口。
并发数使用配置 `sync_workers`（默认 4，可用环境变量 `SYNC_WORKERS` 调低），每次请求随机等待 1～2 秒，超时为 30 秒。
主线程逐股写入 `stock_hot_daily`，以本次接口数据为准覆盖同日同股票的记录，可重跑。
名称取股票池当前名称，`price`、`change_pct` 留空，`source` 为 `Hithink`，只保存接口实际返回的日期点位，不填造缺失日期。
保留表的同日排名唯一约束：若该排名已被其他股票占用，删除冲突旧记录并写入本次数据；删除和写入在同一事务中完成，失败回滚，不影响无冲突记录。请求或写入失败不影响其他股票，最后汇总失败和无数据股票。
有失败时脚本以非零状态退出；限流时可调低并发后重跑。随机延迟不能保证不会被限流。

每个信号形态入口都可以单独运行并查看本地结果，例如：

```bash
uv run python -m backend.quant.signal.patterns.breakout_pullback_n
uv run python -m backend.quant.signal.patterns.panic_reversal_v
uv run python -m backend.quant.signal.patterns.recent_volume_breakout
uv run python -m backend.quant.signal.patterns.today_confirmed_breakout
uv run python -m backend.quant.signal.patterns.today_confirmed_breakout --trade-date 2025-09-11
```

各信号形态入口分别保留自己的数据读取、Rich 终端展示和 `__main__` 入口。

## 命令入口

- `backend/run.py`：启动 FastAPI；
- `backend/scripts/latest/sync_stock_list.py`：同步股票列表；
- `backend/scripts/latest/sync_hk_us_stock_pools.py`：幂等更新港股、美股人工股票池；
- `backend/scripts/latest/sync_stock_daily_basic.py`：同步最近 3 日每日指标；
- `backend/scripts/latest/sync_stock_daily_bars.py`：同步最近 3 日日 K，供 `quant-sync` 使用；
- `backend/scripts/latest/sync_hk_us_daily_bars.py`：通过 Futu OpenD 同步港美股最近 3 日日 K；
- `backend/scripts/latest/sync_hot_stock.py`：分别向三个市场数据库同步当天股票热度；
- `backend/scripts/history/`：每日指标、日 K 和 A 股热度的历史补数入口。

```bash
uv run quant-api
uv run quant-sync
uv run quant-backtest
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
| 增加或调整选股信号 | `quant/signal/patterns/` 与 `quant/signal/` |
| 增加或调整买卖规则、交易策略 | `quant/strategy/` |
| 增加模拟执行或绩效评估 | `quant/backtest/` |
| 增加股票池或通用过滤 | `quant/stock/` |
