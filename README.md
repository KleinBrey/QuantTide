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
│   ├── tests/               # 后端测试
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

同步脚本会自动初始化三个市场数据库和所需数据表。`cn_market.duckdb` 只保存 A 股数据，港股和美股分别保存在 `hk_market.duckdb` 与 `us_market.duckdb`。依次同步股票列表、日 K 和当日股票热度：

```bash
uv run python -m backend.scripts.sync_stock_list_db
uv run python -m backend.scripts.init_hk_us_stock_pools
uv run quant-sync
uv run python -m backend.scripts.sync_hk_us_daily_k_db
uv run python -m backend.scripts.sync_hot_stock_db
```

`quant-sync` 会显示交互式菜单，可选择：

- 最近 3 个自然日，每批 100 只；
- 最近 60 个自然日，每批 50 只；
- 最近 365 个自然日，每批 10 只。

港股和美股日 K 同步脚本同样提供 3、60、365 个自然日选项；它会从两个
市场各自的 `stocks` 表读取股票，并通过本机 Futu OpenD 写入对应的
`daily_bars` 表。

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

- 每月 1 日 10:00：更新股票列表；
- 周一至周五 18:00：更新股票热度；
- 周一至周五配置时间：更新最近 3 个自然日的日 K；
- 每周六 09:00：校准最近 60 个自然日的日 K；
- 每月 1 日 10:00：校准最近 365 个自然日的日 K。

数据仅用于研究，不构成投资建议。
