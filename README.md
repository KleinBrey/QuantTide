# QuantTide（量潮）

QuantTide 是一个本地 A 股量化投研平台，使用 FastAPI、DuckDB、Pandas 和 APScheduler，提供股票基础信息、日 K、股票热度同步、自然语言选股以及量化策略实验能力。

## 项目结构

```text
quanttide/
├── backend/
│   ├── app/
│   │   ├── api/             # FastAPI 路由和依赖
│   │   ├── config/          # 应用与调度配置
│   │   ├── database/        # DuckDB 连接、表结构和辅助 SQL
│   │   ├── jobs/            # 定时任务
│   │   ├── provider/        # Tushare、HiThink、AkShare、问财
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
│   ├── cn_market.duckdb       # A 股
│   ├── hk_market.duckdb       # 港股
│   └── us_market.duckdb       # 美股
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

港美股股票池由独立脚本手动维护，不参与自动同步。首次初始化或添加股票时，
修改 `backend/scripts/init_hk_us_stock_pools.py` 中的 `HK_STOCKS`、`US_STOCKS` 后运行：

```bash
uv run python -m backend.scripts.init_hk_us_stock_pools
```

脚本可重复执行，添加或更新名单内的股票，保留数据库中的其他股票；
从脚本名单移除股票不会删除数据库记录。

依次同步 A 股股票列表、日 K 和当日股票热度：

```bash
uv run python -m backend.scripts.latest.sync_daily_stocks
uv run python -m backend.scripts.latest.sync_daily_basic
uv run quant-sync
uv run python -m backend.scripts.latest.sync_hk_us_daily_bars
uv run python -m backend.scripts.latest.sync_daily_hot
```

同步入口按用途拆分到 `backend/scripts/latest/` 和 `backend/scripts/history/`。
`quant-sync` 指向 `latest.sync_daily_bars`，直接更新最近 3 个自然日的
A 股日 K，按范围内的交易日逐日获取全市场数据。`latest` 下的每日指标和港美股日 K 同样直接更新最近 3 日，
热度脚本同步当天数据，股票池脚本同步最近 3 个自然日内的完整交易日快照。

需要补历史数据时使用：

```bash
uv run python -m backend.scripts.history.sync_daily_stocks
uv run python -m backend.scripts.history.sync_daily_basic
uv run python -m backend.scripts.history.sync_daily_bars
uv run python -m backend.scripts.history.sync_hk_us_daily_bars
uv run python -m backend.scripts.history.sync_daily_hot
```

历史股票池入口可选最近 60、180（半年）、365（一年）、1095（三年）个自然日（含今天），每次重新拉取并覆盖已有快照，
历史股票池通过菜单选择范围，最多 10 个线程并发同步。
A 股历史每日指标和日 K 入口提供最近 60、180、365、1095 个自然日选项，A 股日 K 按交易日拉取全市场数据，不依赖本地股票池；历史热度入口可选最近 60、365 个自然日（含今天），补齐 A 股排名。
港美股日 K 从两个市场各自的 `stocks` 表读取股票，通过 `YFinanceProvider`
从 Yahoo Finance 获取，写入对应的 `daily_bars` 表，无需启动 Futu OpenD。
价格使用 Yahoo 自动复权，成交量保留上游口径，成交额 `amount` 写入 NULL，
来源为 `YFinance`。同步默认最多 2 个并发请求，请求失败时指数退避重试。

已有 Futu 历史数据不会因代码升级自动改写。首次切换应先备份两个市场数据库，
再通过历史入口补齐整个保留区间，避免拼接不同来源的复权行情；超过 365 天时可
直接调用 `sync_hk_us_daily_bars(lookback_days=所需自然日数)`。
Yahoo 自动复权与 Futu 前复权不保证一致，分红、拆股后需重刷保留的历史区间；
日常最近 3 日同步不会自动重算更早的价格。日 K 可能包含当天未收盘的数据，
用于收盘策略时应在对应市场收盘后运行。

## 启动 API

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

## 定时任务

FastAPI 启动时默认注册以下任务：

- 工作日 18:00：保存最新交易日股票池快照；
- 周一至周五 18:00：更新股票热度；
- 周一至周五配置时间：更新最近 3 个自然日的日 K；
- 每周六 09:00：校准最近 60 个自然日的日 K；
- 每月 1 日 10:00：校准最近 365 个自然日的日 K。

数据仅用于研究，不构成投资建议。

A 股库表名统一为 `daily_stocks`、`daily_bars`、`daily_basic`、`daily_hot`。
`daily_stocks` 按 `(trade_date, symbol)` 保存历史股票池，普通股票列表读取最新完整快照。
历史股票池按所选最近时间范围重新拉取，以新快照完整替换对应交易日的旧数据。
回测按当日或此前最近快照选股，市值、热度与行情禁止引用未来日期。
历史补数及缺失数据规则见 [后端说明](backend/README.md)。
