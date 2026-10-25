"""按脚本注册表执行任务；不负责读写任务配置。"""

import threading
from importlib import import_module

from backend.scripts.registry import SCRIPTS

# 手动任务、定时任务和数据库同步接口共用，避免同时写入 DuckDB。
database_sync_lock = threading.Lock()


def run_script(script_id: str, params: dict):
    """执行脚本；失败（包括部分失败）由脚本抛出异常。"""
    # 注册表保存“模块路径:函数名”，直到执行时才加载脚本。
    module_name, function_name = SCRIPTS[script_id]['run'].split(':')
    module = import_module(module_name)
    function = getattr(module, function_name)
    function(**params)
