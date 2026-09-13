# Pandas 项目化系列教程

这套教程不是把 Pandas API 挨个背一遍，而是围绕本项目的 A 股数据处理流程来学习：

```text
股票列表 + 日 K 数据
        ↓
读取和检查
        ↓
筛选、清洗、分组、关联
        ↓
计算涨跌幅、均线和量比
        ↓
得到候选股票
```

代码刻意保持简单。前 8 节使用本目录的迷你 CSV，不联网，也不修改项目数据；第 9 节开始以只读方式访问项目现有的 `data/cn_market.duckdb`。

## 运行环境

在项目根目录执行：

```bash
source .venv/bin/activate
python toturial/pandas/00_series_dataframe.py
```

如果尚未安装依赖：

```bash
python -m pip install pandas duckdb
```

建议按编号学习。每运行一节，都尝试修改一个筛选条件或计算窗口，再观察结果。

## 课程目录

| 课程 | 主要内容 | 在本项目中的用途 |
| --- | --- | --- |
| `00_series_dataframe.py` | Series、DataFrame、索引、列 | 理解行情表在内存中的样子 |
| `01_read_csv_inspect.py` | 读取 CSV、数据类型、快速检查 | 接收外部行情数据后的第一步 |
| `02_selection_filter_sort.py` | 选列、筛选、排序、`loc` | 根据价格、成交量等条件选股 |
| `03_groupby_aggregate.py` | `groupby`、`agg`、`transform` | 按股票统计交易天数、均价、成交量 |
| `04_merge_concat_apply.py` | `merge`、`concat`、`map` | 合并股票名称与日 K，追加新行情 |
| `05_cleaning_dates.py` | 缺失值、重复值、日期、数值转换 | 清洗第三方数据源返回的脏数据 |
| `06_vectorized_calculation.py` | 列运算、`shift`、涨跌幅、振幅 | 生成日 K 衍生指标 |
| `07_rolling_indicators.py` | `rolling`、移动均线、均量 | 计算 MA 和成交量趋势 |
| `08_read_project_duckdb.py` | Pandas + DuckDB | 读取项目真实股票和日 K 数据 |
| `09_analysis_pipeline.py` | 函数化的数据分析流程 | 把读取、清洗、计算、输出连起来 |
| `10_volume_breakout_project.py` | 5 日/前 20 日量比、5 日涨幅 | 复刻项目放量选股策略的核心部分 |

`data/stocks.csv` 和 `data/daily_bars.csv` 是教学数据，可以放心修改。

## 两个数据库字段为什么不同

项目目前有两套代码：

- `backend/app` 使用 `data/cn_market.duckdb`，日 K 日期列叫 `date`。

本教程贴合当前的 `backend/app` 和它的放量策略，所以第 8～10 节读取 `cn_market.duckdb`，并统一使用日 K 的 `date` 字段。

## 推荐练习

1. 把第 2 节的筛选条件改成“成交量大于 1000 且收盘价高于开盘价”。
2. 在第 6 节新增 `amount_change_pct`，计算成交额的日变化率。
3. 把第 7 节的 3 日均线改成 5 日均线。
4. 在第 9 节把股票代码换成你关注的三只股票。
5. 在第 10 节调整 `MIN_VOLUME_RATIO` 和 `MIN_RETURN_5D_PCT`，比较候选数量。

教程只用于学习数据分析，不构成投资建议。
