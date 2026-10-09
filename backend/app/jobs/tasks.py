"""按脚本注册表执行任务；不负责读写任务配置。"""

import threading
from importlib import import_module

from backend.scripts.registry import SCRIPTS

# 手动任务、定时任务和旧同步接口共用，避免同时写入 DuckDB。
database_sync_lock = threading.Lock()


def run_script(script_id: str, params: dict):
    # 注册表保存“模块路径:函数名”，直到执行时才加载脚本。
    module_name, function_name = SCRIPTS[script_id]['run'].split(':')
    module = import_module(module_name)
    function = getattr(module, function_name)
    result = function(**params)

    # 港美股脚本通过返回值报告部分失败，需要将它转为任务失败。
    if script_id == 'hk_us_daily_bars':
        failures = []
        for market, outcome in result.items():
            if outcome['failed_symbols']:
                symbols = ', '.join(outcome['failed_symbols'])
                failures.append(f'{market}：{symbols}')
        if failures:
            raise RuntimeError('部分股票同步失败；' + '；'.join(failures))
