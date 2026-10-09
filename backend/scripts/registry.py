"""脚本注册表；run 使用完整模块路径:入口函数，按需导入执行。"""

SCRIPTS: dict[str, dict[str, object]] = {
    # 日常更新和历史补数共用入口，只需调整 lookback_days。
    "daily_stocks": {
        "name": "A 股股票池",
        "run": "backend.scripts.sync_daily_stocks:sync_daily_stocks",
        "params": {"lookback_days": 3},
    },
    "daily_basic": {
        "name": "A 股每日指标",
        "run": "backend.scripts.sync_daily_basic:sync_daily_basic",
        "params": {"lookback_days": 3},
    },
    "daily_bars": {
        "name": "A 股日 K 线",
        "run": "backend.scripts.sync_daily_bars:sync_daily_bars",
        "params": {"lookback_days": 3},
    },
    "hk_us_daily_bars": {
        "name": "港美股日 K 线",
        "run": "backend.scripts.sync_hk_us_daily_bars:sync_hk_us_daily_bars",
        "params": {"lookback_days": 365},
    },
    "daily_hot": {
        "name": "A 股、港股、美股实时热度",
        "run": "backend.scripts.sync_daily_hot:sync_daily_hot",
    },
    # 历史热度使用独立接口，只支持 A 股，不能与三市场实时热度合并。
    "cn_daily_hot": {
        "name": "A 股历史热度",
        "run": "backend.scripts.sync_cn_daily_hot:sync_cn_daily_hot",
        "params": {"lookback_days": 365},
    },
}


def script_catalog() -> list[dict]:
    """供前端选择脚本；读取注册表不会导入或运行同步脚本。"""
    return [
        {"id": script_id, "name": script["name"], "params": script.get("params", {})}
        for script_id, script in SCRIPTS.items()
    ]
