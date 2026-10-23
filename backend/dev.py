"""Start the local API and frontend together, and stop them as a unit."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent.parent


def _stop(processes: list[subprocess.Popen]) -> None:
    # npm and Vite have descendants; signal each entire session we created.
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    for process in processes:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def main() -> int:
    npm = shutil.which("npm")
    if npm is None:
        print("未找到 npm，请先安装 Node.js。", file=sys.stderr)
        return 1
    if not (ROOT / "frontend/node_modules/.bin/vite").exists():
        print("前端依赖未安装，请先运行：cd frontend && npm install", file=sys.stderr)
        return 1
    for port in (8001, 5173):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                print(f"无法使用端口 {port}，请检查是否已有服务运行：{exc}", file=sys.stderr)
                return 1

    processes: list[subprocess.Popen] = []

    def request_stop(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    previous_handlers = {
        sig: signal.signal(sig, request_stop)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }
    try:
        print("正在启动 QuantTide：前端 http://127.0.0.1:5173，API http://127.0.0.1:8001/docs", flush=True)
        print("浏览器将自动打开；按 Ctrl+C 同时停止前后端。", flush=True)
        for command in (
            [sys.executable, "-m", "backend.run"],
            [npm, "--prefix", "frontend", "run", "dev", "--", "--strictPort"],
        ):
            processes.append(subprocess.Popen(command, cwd=ROOT, start_new_session=True))
        while True:
            for name, process in zip(("后端", "前端"), processes):
                code = process.poll()
                if code is not None:
                    print(f"{name}已退出（退出码 {code}），正在停止另一服务。", file=sys.stderr)
                    return code if code > 0 else 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n正在停止前后端…", flush=True)
        return 0
    except OSError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1
    finally:
        # A repeated Ctrl+C must not interrupt cleanup and leave child servers behind.
        for sig in previous_handlers:
            signal.signal(sig, signal.SIG_IGN)
        _stop(processes)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
