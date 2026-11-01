# QuantTide（量潮）

## 项目介绍

QuantTide 是一个本地量化投研平台，使用 FastAPI、SQLite、DuckDB、Pandas 和 APScheduler，支持 A 股、港股、美股、期货和加密货币的数据同步、自选分组、股票热度、自然语言选股及量化策略实验。

## 项目结构

```text
QuantTide/
├── backend/
│   ├── app/
│   │   ├── api/          # API 路由和依赖
│   │   ├── config/       # 应用配置
│   │   ├── database/     # 数据库连接和表结构
│   │   │   ├── duckdb/  # 行情数据库
│   │   │   └── sqlite/  # 应用数据库
│   │   ├── jobs/         # 定时任务
│   │   ├── provider/     # 数据源接入
│   │   ├── repository/   # 数据访问
│   │   ├── schemas/      # API 数据模型
│   │   ├── services/     # 同步和业务逻辑
│   │   ├── utils/        # 通用工具
│   │   └── main.py       # FastAPI 入口
│   ├── quant/
│   │   ├── backtest/     # 回测引擎
│   │   ├── factor/       # 因子计算
│   │   ├── signal/       # 信号与形态识别
│   │   ├── stock/        # 股票池与筛选
│   │   └── strategy/     # 量化策略
│   ├── scripts/          # 数据同步脚本
│   ├── tests/            # 后端测试
│   ├── .env              # 本地数据源与应用配置
│   ├── dev.py            # 前后端启动管理
│   ├── run.py            # 后端启动入口
│   └── README.md         # 后端详细说明
├── data/
│   ├── app.sqlite              # 自选分组、任务配置
│   ├── cn_market.duckdb        # A 股
│   ├── hk_market.duckdb        # 港股
│   ├── us_market.duckdb        # 美股
│   ├── futures_market.duckdb   # 期货
│   └── crypto_market.duckdb    # 加密货币
├── frontend/
│   ├── public/           # 公共静态资源
│   ├── src/
│   │   ├── api/          # 后端与数据源请求
│   │   ├── assets/       # 图片、图标
│   │   ├── components/   # 通用组件
│   │   ├── contexts/     # 主题、交易日历等共享状态
│   │   ├── features/     # 行情、热度、信号、回测、数据同步等功能
│   │   ├── hooks/        # 通用 React Hooks
│   │   ├── layouts/      # 页面布局
│   │   ├── pages/        # 页面入口
│   │   ├── routes/       # 路由配置
│   │   ├── shadcn/       # UI 基础组件与工具
│   │   ├── utils/        # 前端工具
│   │   ├── App.jsx       # 应用组件
│   │   └── main.jsx      # 前端启动入口
│   ├── .env              # 本地前端配置
│   ├── package.json      # 前端依赖与运行命令
│   └── vite.config.js    # Vite 配置
├── start.command         # 一键启动
├── pyproject.toml        # Python 依赖配置
├── uv.lock               # Python 依赖锁定
└── README.md
```

## 安装

需要 Python 3.11+、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和 Node.js 22+（含 npm）。在项目根目录安装依赖：

```bash
uv sync
npm --prefix frontend install
```

`uv sync` 会自动创建 `.venv`，使用 `uv run` 执行命令即可，无需手动激活。

## 初始化

使用 Tushare、问财等数据源前，在 `backend/.env` 中配置对应的 Token 或 API Key。

启动后端或执行同步脚本时，会自动创建所需数据库和表，无需手动建表。

首次启动后，在“数据同步”页面的“任务列表”中添加并执行同步任务：

- A 股先同步股票列表，再同步日 K、每日指标或热度。
- 港股、美股和加密货币先在对应市场页面添加池成员，再同步日 K。
- 期货先运行“期货市场同步”获取合约资料，再添加合约并重新同步日 K。

## 运行

以下命令均在项目根目录执行。

**同时启动前后端**：macOS 可双击 `start.command`，或在终端运行：

```bash
./start.command
```

也可以直接运行启动模块，效果相同：

```bash
uv run python -m backend.dev
```

以上方式会自动清理占用端口的进程并打开浏览器，按 `Ctrl+C` 同时停止前后端。

**分别启动前后端**：打开两个终端，在第一个终端启动后端：

```bash
uv run quant-api
```

在第二个终端启动前端：

```bash
npm --prefix frontend run dev
```

分别启动时，按 `Ctrl+C` 停止对应服务；端口占用需自行处理。

访问地址：

- 页面：[http://127.0.0.1:5173](http://127.0.0.1:5173)
- API 文档：[http://127.0.0.1:18765/docs](http://127.0.0.1:18765/docs)
