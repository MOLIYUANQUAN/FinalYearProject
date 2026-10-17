#!/usr/bin/env python3
"""打开 Friday：服务没开或代码变了才（重）启动，然后把 Friday 窗口拿到最前面。

  双击仓库根目录的 Friday.cmd（或桌面 / 开始菜单里的 Friday）
  python scripts/open_agent.py [--no-window] [--restart] [--stop] [--resident]

--resident 由开机启动项使用：常驻后台、保证服务在跑，并监听 Ctrl+Alt+F。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import desktop  # noqa: E402
from src.version import code_version  # noqa: E402

PORT = 8765
LOG_DIR = ROOT / "data" / "logs"
RESIDENT_PID = LOG_DIR / "resident.pid"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200

# 系统代理可能没开却拦着 127.0.0.1，本地请求一律直连
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    ctypes.windll.user32.MessageBoxW(None, message, desktop.APP_NAME, 0x10)
    sys.exit(1)


def _health() -> dict | None:
    try:
        from src.config import get_access_token

        request = urllib.request.Request(f"{desktop.BASE_URL}api/health")
        token = get_access_token()
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        with _local.open(request, timeout=1) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


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


def _kill(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=CREATE_NO_WINDOW)


def _stop_server() -> None:
    for pid in _listening_pids():
        _kill(pid)
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
        if _health():
            return True
        time.sleep(0.25)
    return False


def _ensure_server(restart: bool = False) -> None:
    running = _health()
    if running and not restart and running.get("code_version") == code_version():
        return
    _stop_server()
    _start_server()
    if not _wait_until_up():
        _fail("Friday 没能启动，看 data\\logs\\server.err.log。")


def stop_resident() -> None:
    try:
        pid = int(RESIDENT_PID.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if pid != os.getpid():
        _kill(pid)
    RESIDENT_PID.unlink(missing_ok=True)


def _resident() -> None:
    _ensure_server()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RESIDENT_PID.write_text(str(os.getpid()), encoding="utf-8")

    def on_press() -> None:
        _ensure_server()
        desktop.toggle_window()

    if not desktop.listen_hotkey(on_press):
        # 已有一个常驻实例在听，或者组合键被别的软件占了
        RESIDENT_PID.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Open {desktop.APP_NAME}")
    parser.add_argument("--stop", action="store_true", help="stop the local server and the hotkey listener")
    parser.add_argument("--restart", action="store_true", help="restart even if the code is unchanged")
    parser.add_argument(
        "--no-window", "--no-browser", dest="no_window", action="store_true",
        help="make sure the server is up without opening the window",
    )
    parser.add_argument("--resident", action="store_true", help=f"stay in the background and listen for {desktop.HOTKEY_LABEL}")
    args = parser.parse_args()

    if args.stop:
        stop_resident()
        _stop_server()
        return
    if args.resident:
        _resident()
        return
    _ensure_server(args.restart)
    if not args.no_window:
        desktop.show_window()


if __name__ == "__main__":
    main()
