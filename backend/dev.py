"""Start the local API and frontend together, and stop them as a unit."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent.parent
PORT_RELEASE_TIMEOUT = 5


def _port_available(port: int) -> bool:
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                return False
            raise
    return True


def _listener_pids(port: int) -> set[int]:
    lsof = shutil.which("lsof")
    if lsof is None:
        raise RuntimeError("未找到 lsof，无法自动清理占用端口的进程。")
    result = subprocess.run(
        [lsof, "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    # lsof returns 1 when no listeners remain (e.g. they just exited).
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise RuntimeError(f"查询端口 {port} 失败：{result.stderr.strip()}")
    return {int(pid) for pid in result.stdout.split()}


def _wait_for_port(port: int) -> bool:
    deadline = time.monotonic() + PORT_RELEASE_TIMEOUT
    while not _port_available(port):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def _release_port(port: int) -> None:
    if _port_available(port):
        return
    pids = _listener_pids(port)
    if os.getpid() in pids:
        raise RuntimeError(f"当前启动进程正在占用端口 {port}，无法自动停止自身。")
    for pid in sorted(pids):
        print(f"端口 {port} 被进程 {pid} 占用，正在停止…", flush=True)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if _wait_for_port(port):
        print(f"端口 {port} 已释放。", flush=True)
        return
    # Only force-stop the original listeners that still occupy this port.
    for pid in sorted(pids & _listener_pids(port)):
        print(f"进程 {pid} 未退出，正在强制停止…", flush=True)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if not _wait_for_port(port):
        raise RuntimeError(f"端口 {port} 仍被占用，无法启动项目。")
    print(f"端口 {port} 已释放。", flush=True)


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
    try:
        for port in (18765, 5173):
            _release_port(port)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"清理启动端口失败：{exc}", file=sys.stderr)
        return 1

    processes: list[subprocess.Popen] = []

    def request_stop(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    previous_handlers = {
        sig: signal.signal(sig, request_stop)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }
    try:
        print("正在启动 QuantTide：前端 http://127.0.0.1:5173，API http://127.0.0.1:18765/docs", flush=True)
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
