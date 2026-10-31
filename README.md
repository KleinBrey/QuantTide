# QuantTide（量潮）

QuantTide 是一个本地量化投研平台，使用 FastAPI、SQLite、DuckDB、Pandas 和 APScheduler，提供股票基础信息、日 K、自选股分组、股票热度同步、自然语言选股以及量化策略实验能力。

## 项目结构

```text
quanttide/
├── backend/
│   ├── app/
│   │   ├── api/             # FastAPI 路由和依赖
│   │   ├── config/          # 应用与调度配置
│   │   ├── database/        # 按 DuckDB、SQLite 分目录管理连接和表结构
│   │   ├── jobs/            # 定时任务
│   │   ├── provider/        # Tushare、HiThink、AkShare、Futu、通达信、Yahoo、问财
│   │   ├── repository/      # DuckDB 数据访问
│   │   ├── schemas/         # Pydantic API 模型
│   │   ├── services/        # 数据格式化和同步业务
│   │   ├── strategy/        # 选股策略
│   │   ├── utils/           # 日期、股票代码工具
│   │   ├── view/            # Rich 命令行展示
│   │   └── main.py          # FastAPI 入口
│   ├── scripts/             # 股票列表、日 K、热度同步脚本
│   └── run.py               # API 快捷启动入口
├── data/
│   ├── app.sqlite             # 自选分组、成员和排序等业务数据
│   ├── cn_market.duckdb       # A 股
│   ├── hk_market.duckdb       # 港股
│   ├── us_market.duckdb       # 美股
│   └── crypto_market.duckdb   # 加密货币（币安现货）
├── frontend/
├── pyproject.toml
└── README.md
```

## 安装

要求 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。

```bash
uv sync
```

运行依赖和开发依赖统一在根目录 `pyproject.toml` 中声明，精确版本由 `uv.lock` 锁定。`uv sync` 会创建 `.venv` 并默认安装 `dev` 依赖组。

如果你还想手动激活，重新生成后：

```bash
source .venv/bin/activate
```

再：

```bash
echo $VIRTUAL_ENV
```

## 初始化和同步

同步脚本会自动初始化三个市场数据库和所需数据表。`cn_market.duckdb` 只保存 A 股数据，港股和美股分别保存在 `hk_market.duckdb` 与 `us_market.duckdb`。

FastAPI 启动时自动创建港股、美股的空股票池，已有成员保持不变。
启动后在对应市场行情页添加或移除股票，再执行港美股日 K 同步，无需维护脚本名单。

依次同步 A 股股票列表、日 K 和当日股票热度：

```bash
uv run python -m backend.scripts.sync_daily_stocks
uv run python -m backend.scripts.sync_daily_basic
uv run quant-sync
uv run python -m backend.scripts.sync_hk_daily_bars
uv run python -m backend.scripts.sync_us_daily_bars
uv run python -m backend.scripts.sync_realtime_hot
```

同步脚本统一放在 `backend/scripts/`。直接运行会显示日期选择菜单：60、180、365、1095 日，输入 `e` 退出。
任务页面通过“同步最近多少个自然日”配置天数；API 和定时任务直接调用同步函数，传入 `lookback_days`，不会显示菜单。

热度保留两个独立入口：`sync_realtime_hot` 获取 A 股、港股、美股实时热度；
`sync_daily_hot` 只获取 A 股历史热度排名，直接运行可选择 60、365 日或退出：

```bash
uv run python -m backend.scripts.sync_daily_hot
```

所有天数均含今天。股票池按交易日覆盖快照，最多 10 个线程并发同步；
A 股每日指标和日 K 按交易日获取全市场数据。
港美股日 K 从 SQLite 中各市场的 `stock_pool` 默认分组读取成员，通过 `YFinanceProvider`
从 Yahoo Finance 获取，写入对应的 `daily_bars` 表，无需启动 Futu OpenD。
价格使用 Yahoo 自动复权，成交量保留上游口径，成交额 `amount` 写入 NULL，
来源为 `YFinance`。同步默认最多 2 个并发请求，请求失败时指数退避重试。

已有 Futu 历史数据不会因代码升级自动改写。首次切换应先备份两个市场数据库，
再通过任务页面设置同步天数，补齐整个保留区间，避免拼接不同来源的复权行情。
Yahoo 自动复权与 Futu 前复权不保证一致，分红、拆股后需重刷保留的历史区间；
日常最近 3 日同步不会自动重算更早的价格。日 K 可能包含当天未收盘的数据，
用于收盘策略时应在对应市场收盘后运行。

## 一键启动前后端

首次安装依赖：

```bash
uv sync
cd frontend && npm install
```

之后在项目根目录运行：

```bash
./start.command
```

macOS 也可以在 Finder 中双击根目录的 `start.command`。
前后端会在同一个终端启动，浏览器自动打开 <http://127.0.0.1:5173>，
API 文档位于 <http://127.0.0.1:8001/docs>。按 `Ctrl+C` 同时停止两个服务；
任一服务退出也会自动停止另一服务。端口被占用时会提示，避免重复启动。

也可以运行 `uv run python -m backend.dev`，或在 VS Code 的“终端 → 运行任务”中选择“启动：完整看板”。

## 单独启动 API

```bash
uv run quant-api
```

也可以直接启动 Uvicorn：

```bash
uv run uvicorn backend.app.main:app \
  --host 127.0.0.1 --port 8001 --reload
```

- Swagger：<http://127.0.0.1:8001/docs>
- `GET /api/stocks-list`：读取本地股票列表
- `POST /api/stocks-list`：从 Tushare 更新股票列表

## 自选股与分组

港股、美股行情页顶部提供横跨股票列表和 K 线的自选分组栏。默认选中本市场的
`stock_pool`；点击右侧下拉箭头可新建、重命名、删除和排序分组。
分组标签和股票均可拖拽排序，股票右键菜单可将同一股票加入其他分组。
同一分组内禁止重复添加同一市场、同一代码的股票。

任务配置和自选分组存入 `data/app.sqlite` 的 `tasks`、`watchlist_groups`、`watchlist_items` 表。
分组表增加 `market` 和 `is_default`，用于区分 HK、US 同名的 `stock_pool`；
`market` 为空的普通分组可跨市场使用，行情页只展示本市场成员。
界面新建的分组归属当前市场；API 可通过 `market: null` 创建跨市场分组。
SQLite 不复制股票名称或行情，这些信息按成员的 CN/HK/US 市场从 DuckDB 读取。

FastAPI 启动时确保 HK、US 的 `stock_pool` 默认分组存在，不自动添加股票。
HK、US 默认分组不可删除或重命名，CN 没有 `stock_pool`。移出自选、删除普通
分组不会删除 DuckDB 基础信息或历史行情。

可通过 `APP_DATABASE_PATH` 配置 SQLite 路径；每次连接开启外键，删除普通分组时
级联删除对应成员。已有后端进程需要重启以加载这些接口：

- `GET/POST /api/watchlists/groups`：列出或新建分组。
- `PATCH/DELETE /api/watchlists/groups/{id}`：重命名或删除普通分组。
- `PUT /api/watchlists/groups/order`：提交全部分组 ID 的顺序。
- `GET/POST /api/watchlists/groups/{id}/items`：读取或添加成员。
- `DELETE /api/watchlists/groups/{id}/items/{item_id}`：移出成员。
- `PUT /api/watchlists/groups/{id}/items/order`：提交该分组全部成员 ID 的顺序。
- `GET /api/watchlists/stocks/search?q=名称或代码&market=HK`：查询 DuckDB 股票基础信息。
- `GET/POST/DELETE /api/market-stocks`：港美股默认分组增删入口。

## 定时任务

前端“任务列表”支持新增、编辑、删除、启停调度、立即执行和拖动排序，配置保存在 SQLite。
拖动任务左侧手柄即可调整顺序，松开后自动保存到 `tasks.sort_order`，刷新或重启后保持顺序。
新增任务追加到末尾；旧数据库启动时自动补齐排序字段并保留原有 ID 顺序。
`PUT /api/tasks/order` 接收 `{"ids": [任务ID, ...]}`，必须包含当前全部任务且不能重复。
首次启动只创建空的 `tasks` 表，不预填任何任务。用户在前端点击“新增任务”配置脚本、参数和定时规则。
FastAPI 启动时从 `tasks` 表恢复用户保存的调度。

任务可选择注册表中的日常同步或历史补数脚本。
日常更新与历史补数选择同一个脚本，通过任务参数 `lookback_days` 指定天数。
删除任务不会删除行情数据，任务删空后重启仍为空。

数据仅用于研究，不构成投资建议。

A 股库表名统一为 `daily_stocks`、`daily_bars`、`daily_basic`、`daily_hot`。
`daily_stocks` 按 `(trade_date, symbol)` 保存历史股票池，普通股票列表读取最新完整快照。
历史股票池按所选最近时间范围重新拉取，以新快照完整替换对应交易日的旧数据。
回测按当日或此前最近快照选股，市值、热度与行情禁止引用未来日期。
历史补数及缺失数据规则见 [后端说明](backend/README.md)。

加密货币页面位于 `/crypto-market`，可添加币安现货交易对并手动同步最近一年的日 K。
后端启动时自动初始化 `data/crypto_market.duckdb`；日线按 UTC 日期保存，包含当天尚未收盘的行情。


### 期货（默认主力合约）

期货使用 Tushare，复用项目已有的数据源配置。资料与日线独立保存到
`data/futures_market.duckdb`，自选分组仍保存在 `data/app.sqlite`。
数据库初始化只创建当前表结构，不执行历史版本的数据迁移。

1. 在“数据同步”添加并运行“期货市场同步”，先获取主力合约资料；合约池为空时跳过日 K 同步。
2. 打开侧栏“期货”，点击“添加合约”，按名称或代码搜索（例如 RB.SHF）。
3. 再次运行“期货市场同步”任务，先更新合约资料，再同步合约池最近 365 个自然日的日 K；回溯天数可调整，也可设置定时执行。
4. 返回期货页面查看 K 线。支持自选分组、拖动排序、移入分组、移除和日/周/月 K 线。

`fut_basic(fut_type=2)` 返回主力及连续合约，按代码前缀等于 `fut_code` 筛选主力。
Tushare 的 `fut_code` 在 provider 中转换为内部字段 `code`；合约表的
`main_symbol`、`main_name`、`trade_date` 保存主力月合约代码、名称及映射交易日。
资料同步先通过 `fut_trade_cal` 查询最近一个月至今天的开市日期，再通过 `fut_mapping` 获取最近交易日的主力月合约，
关联 `fut_basic(fut_type=1)` 的名称。列表和搜索展示实际合约名称及代码（例如铁矿石2701 / I2701.DCE），
鼠标悬停可查看映射日期；再次运行“期货市场同步”即可更新换月后的显示。
自选成员及 K 线仍使用稳定的主力序列代码，图表标题标明主力名称。
仅保留能映射到具体月份合约的品种；同步后自动移除失去映射的期货资料及分组成员，搜索和重置主力分组也只使用这些品种。
日线调用 `fut_daily`，保存未复权主力连续价格（换月可能产生跳空）；成交量和持仓量单位为手，成交额转换为元。
默认池中的合约是日线同步范围。加入自选分组时也加入默认池；从默认池移除后停止后续同步，历史数据保留。

代码按职责分开：`futures_schema.sql` 定义表，`futures_market_db.py` 负责读写，
`futures_market_service.py` 负责同步，`sync_futures_market.py` 统一提供合约资料和日 K 线任务入口。
运行 `python -m backend.scripts.sync_futures_market` 可选择日 K 线回溯范围。
接口文档：[合约资料](https://tushare.pro/document/2?doc_id=135)、[日线行情](https://tushare.pro/document/2?doc_id=138)。
