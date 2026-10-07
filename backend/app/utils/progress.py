"""项目统一的终端进度展示；业务层只提供任务信息，不设置 tqdm 样式。"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import TextIO, TypeVar

from tqdm import tqdm

T = TypeVar("T")

BAR_FORMAT = (
    "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} {unit} "
    "[耗时 {elapsed} | 剩余 {remaining} | {rate_fmt}{postfix}]"
)


def progress_bar(
    iterable: Iterable[T] | None = None,
    *,
    total: int,
    desc: str,
    unit: str,
    range_text: str | None = None,
    workers: int | None = None,
    file: TextIO | None = None,
    disable: bool = False,
) -> tqdm:
    """输出统一任务说明并创建进度条，支持迭代、手动 update 和 set_postfix。

    total/unit 必须对应迭代项，例如每批完成一次就使用批数和“批”。
    range_text 由调用方提供实际查询范围，避免展示层推断业务日期。
    默认全部写入 stderr；disable 同时关闭任务说明和进度条。
    """
    stream = sys.stderr if file is None else file
    if not disable:
        parts = [desc, f"总计 {total} {unit}"]
        if range_text:
            parts.append(f"范围：{range_text}")
        if workers is not None:
            parts.append(f"最大并发数：{workers}")
        progress_write(" | ".join(parts), file=stream)

    return tqdm(
        iterable,
        total=total,
        desc=desc,
        unit=unit,
        bar_format=BAR_FORMAT,
        dynamic_ncols=True,
        mininterval=0.2,
        leave=True,
        file=stream,
        disable=disable,
    )


def progress_write(message: str, *, file: TextIO | None = None) -> None:
    """在进度条之间输出消息，避免普通 print 打断当前进度行。"""
    tqdm.write(message, file=sys.stderr if file is None else file)
