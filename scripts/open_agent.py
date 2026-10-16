#!/usr/bin/env python3
"""打开 Friday：服务没开或代码变了才（重）启动，然后把 Friday 窗口拿到最前面。

  双击仓库根目录的 Friday.cmd
  python scripts/open_agent.py [--no-window] [--restart] [--stop]
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.version import code_version  # noqa: E402

APP_NAME = "Friday"
PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"
LOG_DIR = ROOT / "data" / "logs"
# 只在第一次打开时摆好窗口；之后的大小位置由浏览器记住，不覆盖他自己的调整
PLACED_MARKER = LOG_DIR / "window-placed"
WINDOW_SIZE = (600, 880)
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
SW_RESTORE = 9
SPI_GETWORKAREA = 0x0030
SWP_NOZORDER = 0x0004

# 系统代理可能没开却拦着 127.0.0.1，本地请求一律直连
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_user32 = ctypes.windll.user32
_user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2：坐标即物理像素


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    _user32.MessageBoxW(None, message, APP_NAME, 0x10)
    sys.exit(1)


def _health() -> dict | None:
    try:
        with _local.open(f"{URL}api/health", timeout=1) as response:
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
        if _health():
            return True
        time.sleep(0.25)
    return False


def _ensure_server(restart: bool) -> None:
    running = _health()
    if running and not restart and running.get("code_version") == code_version():
        return
    _stop_server()
    _start_server()
    if not _wait_until_up():
        _fail("Friday 没能启动，看 data\\logs\\server.err.log。")


def _app_path(exe: str) -> str | None:
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as key:
                path = str(winreg.QueryValue(key, None)).strip('"')
        except OSError:
            continue
        if path and Path(path).is_file():
            return path
    return None


def _app_browser() -> str | None:
    """能开独立应用窗口的浏览器：默认浏览器是 Chrome / Edge 就用它，否则任选其一。"""
    preferred: list[str] = []
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        ) as key:
            prog_id = str(winreg.QueryValueEx(key, "ProgId")[0])
        if prog_id.startswith("ChromeHTML"):
            preferred.append("chrome.exe")
        elif prog_id.startswith("MSEdgeHTM"):
            preferred.append("msedge.exe")
    except OSError:
        pass
    for exe in [*preferred, "chrome.exe", "msedge.exe"]:
        path = _app_path(exe)
        if path:
            return path
    return None


def _find_window() -> int:
    # Chrome / Edge 的应用窗口标题就是页面标题
    return _user32.FindWindowW("Chrome_WidgetWin_1", APP_NAME)


def _place(hwnd: int) -> None:
    """按屏幕缩放摆成竖长的对话窗口，放在工作区正中。"""
    scale = (_user32.GetDpiForWindow(hwnd) or 96) / 96
    area = wt.RECT()
    _user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(area), 0)
    width = min(int(WINDOW_SIZE[0] * scale), area.right - area.left)
    height = min(int(WINDOW_SIZE[1] * scale), area.bottom - area.top - int(40 * scale))
    left = area.left + (area.right - area.left - width) // 2
    top = area.top + (area.bottom - area.top - height) // 2
    _user32.SetWindowPos(hwnd, None, left, top, width, height, SWP_NOZORDER)


def _show_window() -> None:
    hwnd = _find_window()
    if hwnd:
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, SW_RESTORE)
        _user32.SetForegroundWindow(hwnd)
        return
    browser = _app_browser()
    if not browser:
        webbrowser.open(URL)
        return
    subprocess.Popen(
        [browser, f"--app={URL}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS,
    )
    if PLACED_MARKER.exists():
        return
    deadline = time.monotonic() + 5
    while not (hwnd := _find_window()) and time.monotonic() < deadline:
        time.sleep(0.1)
    if hwnd:
        _place(hwnd)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        PLACED_MARKER.write_text("placed once; the browser remembers his size from here\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Open {APP_NAME}")
    parser.add_argument("--stop", action="store_true", help="stop the local server")
    parser.add_argument("--restart", action="store_true", help="restart even if the code is unchanged")
    parser.add_argument(
        "--no-window", "--no-browser", dest="no_window", action="store_true",
        help="make sure the server is up without opening the window",
    )
    args = parser.parse_args()

    if args.stop:
        _stop_server()
        return
    _ensure_server(args.restart)
    if not args.no_window:
        _show_window()


if __name__ == "__main__":
    main()
