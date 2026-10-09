"""项目统一的终端进度展示：多行任务说明、紧凑进度条和完成汇总。"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import TextIO, TypeVar

from tqdm import tqdm

T = TypeVar("T")

BAR_FORMAT = (
    "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} "
    "[{elapsed}<{remaining}, {rate_fmt}]"
)


class SyncProgress(tqdm):
    """保留 tqdm 的迭代和更新接口，把业务统计放到结束汇总。"""

    def __init__(self, *args, task_unit: str, **kwargs):
        self.task_unit = task_unit
        self.show_summary = not kwargs.get("disable", False)
        super().__init__(*args, **kwargs)

    def finish(self, *, written: int, failed: int = 0, empty: int | None = None) -> None:
        """业务处理结束后调用；存在失败时明确显示未完整同步。"""
        if not self.show_summary:
            return
        elapsed = self.format_dict["elapsed"]
        self.close()
        status = "✓ 同步完成" if failed == 0 else "⚠ 同步未完整完成"
        parts = [
            status, f"{self.n:,} {self.task_unit}",
            f"写入 {written:,} 条", f"失败 {failed:,}",
        ]
        if empty is not None:
            parts.append(f"无数据 {empty:,}")
        parts.append(f"耗时 {elapsed:.0f} 秒")
        progress_write("\n" + " | ".join(parts), file=self.fp)


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
) -> SyncProgress:
    """输出多行任务说明；进度条仅显示百分比、数量、时间和速度。

    total/unit 必须对应迭代项。结束时调用 finish(written=..., failed=...) 汇总。
    保留 tqdm 的迭代、update 和 set_postfix 接口，但不在进度条中展示 postfix。
    默认全部写入 stderr；disable 同时关闭任务说明、进度条和汇总。
    """
    stream = sys.stderr if file is None else file
    if not disable:
        lines = [desc]
        if range_text:
            lines.append(f"日期范围：{range_text.replace(' 至 ', ' ~ ')}")
        count_label = {"交易日": "交易日数", "日": "日期数", "只": "股票数", "批": "批次数"}.get(unit, "任务数")
        counts = [f"{count_label}：{total:,}"]
        if workers is not None:
            counts.append(f"最大并发数：{workers}")
        lines.append(" | ".join(counts))
        progress_write("\n".join(lines) + "\n", file=stream)

    return SyncProgress(
        iterable,
        total=total,
        desc="同步进度",
        task_unit=unit,
        unit="日" if unit == "交易日" else unit,
        bar_format=BAR_FORMAT,
        ascii=False,
        dynamic_ncols=True,
        mininterval=0.2,
        leave=True,
        file=stream,
        disable=disable,
    )


def progress_write(message: str, *, file: TextIO | None = None) -> None:
    """在进度条之间输出消息，避免普通 print 打断当前进度行。"""
    tqdm.write(message, file=sys.stderr if file is None else file)
