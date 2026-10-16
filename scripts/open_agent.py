#!/usr/bin/env python3
"""打开 Personal Agent：重启本地服务、等它就绪、打开浏览器。

  双击仓库根目录的 Personal Agent.cmd
  python scripts/open_agent.py [--no-browser] [--stop]
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"
LOG_DIR = ROOT / "data" / "logs"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200

# 系统代理可能没开却拦着 127.0.0.1，本地请求一律直连
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    ctypes.windll.user32.MessageBoxW(None, message, "Personal Agent", 0x10)
    sys.exit(1)


def _listening_pids() -> set[int]:
    try:
        raw = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        ).stdout
    except OSError:
        return set()
    pids: set[int] = set()
    for line in raw.decode(errors="replace").splitlines():
        parts = line.split()
        # 状态列会被系统语言本地化，只认「本地端口 + 对端为 0」的监听行
        if (
            len(parts) >= 5
            and parts[0].upper() == "TCP"
            and parts[1].endswith(f":{PORT}")
            and parts[2].endswith(":0")
            and parts[-1].isdigit()
        ):
            pids.add(int(parts[-1]))
    return pids - {0}


def _stop_server() -> None:
    for pid in _listening_pids():
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
    deadline = time.monotonic() + 5
    while _listening_pids() and time.monotonic() < deadline:
        time.sleep(0.2)


def _start_server() -> None:
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        _fail("缺少 .venv：先运行 python -m venv .venv，再 .venv\\Scripts\\pip install -r requirements.txt")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    with (LOG_DIR / "server.out.log").open("wb") as out, (LOG_DIR / "server.err.log").open("wb") as err:
        subprocess.Popen(
            [str(python), "-m", "src.main"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            env=env,
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        )


def _wait_until_up(timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with _local.open(f"{URL}/api/health", timeout=1) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(0.25)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Open Personal Agent")
    parser.add_argument("--stop", action="store_true", help="stop the local server")
    parser.add_argument("--no-browser", action="store_true", help="restart without opening a tab")
    args = parser.parse_args()

    # 端口上的旧进程可能跑着旧代码（页面会 404），每次都换成新的
    _stop_server()
    if args.stop:
        return
    _start_server()
    if not _wait_until_up():
        _fail("Personal Agent 没能启动，看 data\\logs\\server.err.log。")
    if not args.no_browser:
        webbrowser.open(URL)


if __name__ == "__main__":
    main()
