# FastAPI 项目化系列教程

这套教程围绕本项目的 A 股行情 API 编写，不堆砌概念，而是逐步回答这些实际问题：

```text
怎样创建 API？
  → 怎样接收股票代码和查询条件？
  → 怎样校验输入、约束输出？
  → 怎样拆分路由、注入 Repository？
  → 怎样初始化资源、执行后台任务、测试接口？
  → 怎样读取本地 DuckDB 做一个完整股票 API？
```

教程只位于 `toturial/fastapi`，不会修改其他教程目录。第 0～9 课使用内存数据；第 10 课只读访问项目的 `data/cn_market.duckdb`，不会修改业务数据，也不访问网络。

## 环境与运行

在项目根目录执行：

```bash
source .venv/bin/activate
python toturial/fastapi/00_first_api.py
```

每个脚本默认运行一个很小的接口调用演示，执行完会自动退出。例如：

```bash
python toturial/fastapi/04_http_exception.py
python toturial/fastapi/10_stock_api_project.py
```

想在浏览器中体验第 0 课：

```bash
uvicorn --app-dir toturial/fastapi 00_first_api:app \
  --host 127.0.0.1 --port 8002 --reload
```

然后打开：

- Swagger：<http://127.0.0.1:8002/docs>
- ReDoc：<http://127.0.0.1:8002/redoc>
- 健康检查：<http://127.0.0.1:8002/api/health>

## 课程目录

| 课程 | 主要内容 | 对应本项目 |
| --- | --- | --- |
| `00_first_api.py` | 创建应用、GET 路由、JSON 响应、自动文档 | `backend/app/main.py` |
| `01_path_and_query.py` | 路径参数、查询参数、日期和范围校验 | 股票搜索和日 K 查询 |
| `02_response_model.py` | Pydantic 模型、嵌套响应、`response_model` | `schemas/market.py` |
| `03_request_body.py` | POST 请求体、`Literal`、`Field` 校验 | 触发同步任务 |
| `04_http_exception.py` | 代码标准化、422、404 | `normalize_symbol` 和行情接口 |
| `05_api_router.py` | `APIRouter`、前缀、标签、路由拆分 | `api/routes.py` |
| `06_dependency_injection.py` | `Depends`、Repository、测试替换依赖 | `api/dependencies.py` |
| `07_lifespan_and_state.py` | lifespan、`app.state`、资源初始化和清理 | `backend/app/main.py` |
| `08_background_tasks.py` | 202 响应和 `BackgroundTasks` | `/jobs/run` |
| `09_testing_with_testclient.py` | TestClient、pytest、成功和失败用例 | `backend/tests` |
| `10_stock_api_project.py` | 综合应用：查询真实本地股票与日 K | `data/cn_market.duckdb` |

## 推荐学习方法

1. 先直接运行脚本，看请求状态码和 JSON。
2. 阅读路由函数，找出“输入、处理、输出”三部分。
3. 修改一个参数约束，例如把 `limit` 最大值从 20 改为 5。
4. 故意传错误股票代码，观察 422 和 404 的区别。
5. 完成第 10 课后，再对照项目的 `backend/app` 阅读真实实现。

## FastAPI 与项目分层

```text
客户端请求
    ↓
FastAPI Router       负责 HTTP 参数、状态码和响应
    ↓ Depends
Service              负责业务流程
    ↓
Repository           负责 DuckDB 读写
    ↓
Provider             负责第三方行情接口
```

教程会重点保持这个边界：路由不直接堆积复杂 SQL，Repository 也不负责 HTTP 状态码。

接口与数据仅用于学习，不构成投资建议。
