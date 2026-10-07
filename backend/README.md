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

- `cn_market.duckdb.daily_stocks`：每日完整 A 股股票池，包含 `trade_date DATE NOT NULL`、代码、名称、交易所、市场和来源，主键 `(trade_date, symbol)`；
- `cn_market.duckdb.daily_basic`：每日市值（元），主键 `(symbol, trade_date)`；
- `hk_market.duckdb.stocks`、`us_market.duckdb.stocks`：对应市场的股票代码、名称和来源；
- `daily_bars`：股票日 K，主键为 `symbol + trade_date`；
- `cn_market.duckdb.daily_hot`：问财每日股票热度，主键为 `trade_date + symbol`；
- `hk_market.duckdb.stock_hot_daily`：问财每日港股热度，主键为 `trade_date + symbol`；
- `us_market.duckdb.stock_hot_daily`：问财每日美股热度，主键为 `trade_date + symbol`。

三个市场的热度表统一存储 `rank INTEGER`（正整数，1 为热度最高），接口也返回 `rank`，查询按排名升序排列。问财快照按热度值降序生成排名，A 股历史补齐使用 HiThink 返回的原始排名。策略输出中的 `hot_rank` 直接取自该排名，不再按结果行号重新编号。

热榜同步要求传入完整榜单；在同一事务内删除输入交易日的旧榜单并插入新榜单，失败则回滚，其他日期不受影响。空榜或清洗丢失记录时拒绝更新。新建表保留 `(trade_date, symbol)` 主键，并增加 `(trade_date, rank)` 唯一约束；已有表不会因 `CREATE TABLE IF NOT EXISTS` 自动增加约束，现有表由股票主键和写入前的排名检查防止重复。

### `app/provider/`

- `tushare_provider.py`：股票列表、日 K、复权行情和每日市值指标；
- `hithink_provider.py`：HiThink 股票列表、快照和历史行情；
- `akshare_provider.py`：AkShare 股票列表和历史行情适配；
- `futu_provider.py`：通过本机 Futu OpenD 获取股票列表、快照、历史 K 线和热议榜；
- `yfinance_provider.py`：通过 Yahoo Finance 获取港美股历史 K 线，返回统一的
  `data.item` 结构；支持日/周/月 K、Yahoo 自动复权或关闭自动复权，不支持后复权。
  港股如 `00700.HK` 请求时映射为 `0700.HK`，内部股票代码保持不变；
  日期保留交易所交易日，以项目约定的上海时区午夜编码为 `date_ms`；
  `turnover` 为 None，同步后的 `amount` 为 NULL，`source` 为 `YFinance`；
- `iwencai_provider.py`：问财股票热度查询；
- `example/`：各 Provider 的手动冒烟测试。

Futu OpenD 登录并监听本机 `11111` 端口后，可运行美股热议榜冒烟测试：

```bash
uv run python -m backend.app.provider.example.futu_smoke_test
```

### `app/repository/`

Repository 按物理数据库拆分：

- `cn_market_db.py`：`DailyStockRepository`、`DailyBarRepository`、`DailyBasicRepository`、`DailyHotRepository`，分别对应 A 股四张日频表；
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

- 工作日 18:00 更新最新交易日股票池（Tushare 交易日历确认日期）；
- 工作日 15:00 更新 A 股、港股和美股热度；
- 工作日配置时间更新最近 3 日的日 K；
- 周六 09:00 校准最近 60 日的日 K；
- 每月 1 日 10:00 校准最近 365 日的日 K。

每个任务设置 `max_instances=1` 和 `coalesce=True`，避免同一任务重复运行。

### `app/utils/` 和 `app/view/`

- `utils/`：日期、交易所、股票代码处理，以及统一的并发请求和终端进度展示；
- `view/`：Rich 命令行展示示例。

进度条统一从 `backend.app.utils.progress` 导入，业务代码不直接设置 tqdm 样式：

```python
from backend.app.utils.progress import progress_bar, progress_write

progress = progress_bar(
    as_completed(futures),
    total=len(futures),
    desc="同步历史热度",
    unit="只",
    range_text=f"{start} 至 {end}",
    workers=max_workers,
)
written, failed = 0, 0
for future in progress:
    try:
        result = future.result()
        written += repository.upsert(result)
    except Exception as error:
        failed += 1
        progress_write(f"获取失败：{error}")
progress.finish(written=written, failed=failed)
```

任务说明拆为三行：名称、日期范围、总量与最大并发数。进度条统一使用“同步进度”，
仅展示百分比、完成数、耗时、剩余时间和速度；写入数和失败数由 `finish()` 在结束后单独汇总，
数量使用千位分隔。有失败时显示“未完整完成”。股票使用“只”，交易日速度简写为“日/s”，批量请求使用“批”，
总量必须与实际迭代项一致。`range_text` 和 `workers` 可省略。
返回的进度条仍支持 `with`、`update()` 和 `set_postfix()`，但紧凑格式不显示 postfix。
样式只需修改 `utils/progress.py`；任务说明、进度条和 `progress_write()` 消息
默认统一写入 stderr，`disable=True` 可关闭任务说明、进度条和汇总。

`utils/concurrency.py` 提供 `concurrent_requests()`，封装线程池、请求启动限速锁、
按完成顺序收集结果和线程清理。A 股股票池、每日指标和日 K 服务共用它：

```python
from backend.app.utils.concurrency import concurrent_requests

with concurrent_requests(
    dates,
    provider.fetch_daily_bar,
    max_workers=10,
    request_interval=(0.5, 1.0),
) as results:
    for trade_date, future in results:
        rows = future.result()  # 请求异常在这里抛出，由业务层处理。
        # 格式化及数据库写入由当前调用线程执行。
```

`request_interval` 可传固定秒数或随机范围，传 0 不限制启动间隔。
锁在请求发出前释放，网络请求可并发执行；每次调用独立限速，不跨任务或进程共享。
股票池保留 0.6 秒间隔，每日指标和日 K 保留 0.5～1 秒随机间隔，默认最多 10 个线程。
退出 `with` 时通过 `stop.set()` 立即唤醒正在限速等待的线程，取消尚未启动的任务，等待已放行的请求结束。
限速等待使用 `stop.wait()`，并保留锁内按实际放行时间计算下一次间隔，避免延迟唤醒后集中补发请求。

这里以限制请求频率为主，`max_workers` 表示并发上限，不保证线程始终满载。
设平均启动间隔为 `I > 0`、单次 `fetch` 平均耗时为 `T`，稳定状态下的吞吐上限
约为 `min(1 / I, max_workers / T)`，平均在途请求数约为 `实际吞吐 × T`。
默认间隔平均为 0.75 秒，因此限速吞吐上限约 1.33 次/秒；请求平均耗时 2.6 秒时，
达到该吞吐所需的平均在途数量约为 3.5，而不是 10。

在默认间隔下，维持平均 10 个请求在途需要平均请求耗时约 7.5 秒。
这是稳态估算，不是“低于这个耗时就绝不可能达到 10 并发”的硬阈值，
响应耗时和随机间隔的波动会影响峰值。线程已足够覆盖请求等待时间、限速成为瓶颈后，
继续调大 `max_workers` 通常不会提速；处理和写库也可能限制整体同步速度。

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

## 手动维护港美股股票池

`backend/scripts/init_hk_us_stock_pools.py` 是独立的手动入口，不参与自动同步。
首次初始化或添加股票时，修改文件中的 `HK_STOCKS`、`US_STOCKS` 后执行：

```bash
uv run python -m backend.scripts.init_hk_us_stock_pools
```

脚本可重复执行，添加或更新名单内的股票，保留数据库中的其他股票；
从脚本名单移除股票不会删除数据库记录。

自选分组和股票池成员现在保存在 `data/app.sqlite`，仅使用 `watchlist_groups`
和 `watchlist_items` 两张业务表。HK、US 各有一个不可删除、不可重命名的
`stock_pool` 默认分组；CN 不创建此分组。首次启动自动迁入 DuckDB `stocks`
表中的成员，此后只执行一次，移出的成员不会在重启时恢复。
显式运行上述初始化脚本则会将脚本名单重新加入默认分组。
DuckDB 继续保存股票基础信息和历史行情，港美股日 K 同步读取 SQLite 默认分组成员。
业务 API 位于 `/api/watchlists/groups`，支持分组增删改、成员管理和排序；
`APP_DATABASE_PATH` 可覆盖 SQLite 路径。前端入口在港美股行情页顶部独立分组栏的标签及下拉菜单。

## 外层同步脚本

```bash
# A 股股票列表
uv run python -m backend.scripts.latest.sync_daily_stocks

# 最近 3 个自然日的每日指标和日 K
uv run python -m backend.scripts.latest.sync_daily_basic
uv run python -m backend.scripts.latest.sync_daily_bars
uv run python -m backend.scripts.latest.sync_hk_us_daily_bars

# 股票热度
uv run python -m backend.scripts.latest.sync_daily_hot
```

日常更新入口位于 `backend/scripts/latest/`，直接执行，不再弹出日期选择菜单。
日 K 和每日指标默认更新最近 3 个自然日；股票热度同步当天数据；股票列表
同步最近 3 个自然日内的完整交易日股票池快照。同步脚本会在写入前自动初始化数据库。
每日指标按交易日历过滤休市日，进度总数为范围内的交易日数量；范围内无交易日时直接跳过。

历史补数入口位于 `backend/scripts/history/`。A 股每日指标和日 K 可交互式选择
最近 60、180、365 或 1095 个自然日（含今天），与日常入口共用同步函数；A 股日 K 先查询交易日历，
再按交易日调用 `daily(trade_date="YYYYMMDD")` 拉取全市场数据：

```bash
uv run python -m backend.scripts.history.sync_daily_basic
uv run python -m backend.scripts.history.sync_daily_bars
uv run python -m backend.scripts.history.sync_hk_us_daily_bars
```

补齐 A 股股票池历史热度排名，运行后可选择最近 60 或 365 个自然日（含今天）：

```bash
uv run python -m backend.scripts.history.sync_daily_hot
```

读取 A 股库 `daily_stocks` 在历史区间内出现过的全部股票，每只股票调用一次 HiThink 个股排名走势接口。
并发数使用配置 `sync_workers`（默认 4，可用环境变量 `SYNC_WORKERS` 调低），每次请求随机等待 1～2 秒，超时为 30 秒。
主线程逐股写入 `daily_hot`，以本次接口数据为准覆盖同日同股票的记录，可重跑。
名称取数据日期当日或此前最近完整股票池中的名称，`price`、`change_pct` 留空，`source` 为 `Hithink`，只保存接口实际返回的日期点位，不填造缺失日期。
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
- `backend/scripts/latest/sync_daily_stocks.py`：同步股票列表；
- `backend/scripts/init_hk_us_stock_pools.py`：独立手动初始化或添加港股、美股股票池，可重复执行；
- `backend/scripts/latest/sync_daily_basic.py`：同步最近 3 日每日指标；
- `backend/scripts/latest/sync_daily_bars.py`：同步最近 3 日日 K，供 `quant-sync` 使用；
- `backend/scripts/latest/sync_hk_us_daily_bars.py`：通过 yfinance 同步港美股最近 3 日日 K，
  无需 OpenD；默认最多 2 个并发请求，单股失败记录到 `failed_symbols`；
- `backend/scripts/latest/sync_daily_hot.py`：分别向三个市场数据库同步当天股票热度；
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

## A 股股票池历史与无未来数据约束

```text
cn_market
├── daily_stocks  股票池历史快照
├── daily_bars    股票日 K
├── daily_basic   每日市值指标
└── daily_hot     每日热度排名
```

`DailyStockRepository.get_latest_data()` 读取最新交易日的完整股票池；
`get_table_data()` 返回全部交易日的历史快照；`get_as_of(day)` 读取不晚于指定日期的最近完整快照。
股票池写入要求完整的一日数据，按日期事务替换，因此退池成员不会残留，同一日期重跑不会重复。
港股、美股表名保持现状。

历史股票池使用 [Tushare bak_basic](https://tushare.pro/document/2?doc_id=262)，接口自 2016 年起提供数据，
官方权限要求 5000 积分，单次最多 7000 条。名称来自对应日期，交易所及板块按当日代码判断，
不借用当前 `stock_basic` 的名称或 ST 状态。尚未上市或无法确认上市日期的记录排除。
返回日期不符、空快照、重复代码或达到接口条数上限时拒绝写入并报告失败。

```bash
# 交互选择近 60 日、近半年（180 日）、近一年（365 日）、近三年（1095 日）
uv run python -m backend.scripts.history.sync_daily_stocks
```

股票池最多使用 10 个线程，并发数不超过范围内的交易日数量。
日常与历史股票池脚本共用 `scripts/latest/sync_daily_stocks.py` 组装依赖，API 和定时任务也调用此入口。
历史脚本处理菜单和参数，日常脚本提供共用初始化入口；交易日、快照写入及失败汇总由 `CNMarketService` 负责，线程池和限速交给 `utils/concurrency.py`。
股票池统一调用 `update_daily_stocks(lookback_days=None)`：不传天数同步最新快照，指定天数同步该自然日范围内的交易日；无交易日时跳过。
各交易日并发拉取，保留请求启动间隔限速，数据库由主线程统一写入。
所有范围均截至上海时区今天，不需要输入开始或结束日期。新拉取的完整快照按交易日替换旧数据。

历史日 K 同步不依赖本地股票池，按交易日获取当日全市场行情（含后来退市的股票）。
日 K 请求并发且保留限速，主线程写入；空数据、日期不符或达到 6000 条上限时报告失败，
成功日期仍会保存，重跑按 `(symbol, trade_date)` 更新。历史回测仍需单独补齐股票池快照。
历史快照同步失败会以非零状态退出，失败日期的旧快照保留，已成功日期更新；重跑会重新拉取整个所选范围。
每日列表同步同样使用 `bak_basic`，遇到尚未发布的当日数据会报错并保留已有快照。

数据库初始化直接使用当前表结构建表，已有表与数据保留。

回测 API 和命令行加载历史股票池。确认日先向前找到最近的整日快照，再匹配股票代码和当时名称、板块，
不能逐股寻找最后一条记录来复活已退池成员。没有历史快照则不产生选股信号。
市值按股票向前匹配确认日或此前值，热度按突破日或此前值，缺失热度按放量强度排序。
单日扫描同样禁止使用未来市值或无日期热度；行情指标只依赖当日及此前 K 线。
回测引擎还会将所有输入截断到结束日期；新增策略须遵守 `Strategy` 的逐日因果计算约定。
收盘信号按当日收盘价成交仍是原有回测假设，不等同于盘中可执行价格。
