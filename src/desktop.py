"""Friday 在 Windows 桌面上：独立应用窗口、记住窗口位置、全局快捷键。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import subprocess
import time
import webbrowser
import winreg
from collections.abc import Callable
from pathlib import Path

APP_NAME = "Friday"
URL = "http://127.0.0.1:8765/"
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"
# 浏览器不一定记得应用窗口的大小：新窗口沿用上次看到的位置，没有就用竖长的默认尺寸
WINDOW_STATE = STATE_DIR / "window.json"
WINDOW_SIZE = (600, 880)
HOTKEY_LABEL = "Ctrl+Alt+F"

DETACHED_PROCESS = 0x00000008
SW_MINIMIZE, SW_RESTORE = 6, 9
SPI_GETWORKAREA = 0x0030
SWP_NOZORDER = 0x0004
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
WM_HOTKEY = 0x0312
ASFW_ANY = -1

_user32 = ctypes.windll.user32
_user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2：坐标即物理像素


def find_window() -> int:
    # Chrome / Edge 的应用窗口标题就是页面标题
    return _user32.FindWindowW("Chrome_WidgetWin_1", APP_NAME)


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


def _place_default(hwnd: int) -> None:
    """按屏幕缩放摆成竖长的对话窗口，放在工作区正中。"""
    scale = (_user32.GetDpiForWindow(hwnd) or 96) / 96
    area = wt.RECT()
    _user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(area), 0)
    width = min(int(WINDOW_SIZE[0] * scale), area.right - area.left)
    height = min(int(WINDOW_SIZE[1] * scale), area.bottom - area.top - int(40 * scale))
    left = area.left + (area.right - area.left - width) // 2
    top = area.top + (area.bottom - area.top - height) // 2
    _user32.SetWindowPos(hwnd, None, left, top, width, height, SWP_NOZORDER)


def _on_screen(left: int, top: int, right: int, bottom: int) -> bool:
    x0 = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y0 = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    x1 = x0 + _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    y1 = y0 + _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return right - left >= 200 and bottom - top >= 200 and x0 <= left < x1 - 100 and y0 <= top < y1 - 100


def _rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wt.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def _remember(hwnd: int) -> None:
    if _user32.IsIconic(hwnd) or _user32.IsZoomed(hwnd):
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    WINDOW_STATE.write_text(json.dumps(list(_rect(hwnd))), encoding="utf-8")


def _settle(hwnd: int, timeout: float = 1.5) -> None:
    """浏览器刚建窗口时还会自己再摆一次位置：等它停下来再动。"""
    deadline = time.monotonic() + timeout
    last, steady = None, 0
    while time.monotonic() < deadline and steady < 3:
        current = _rect(hwnd) if _user32.IsWindowVisible(hwnd) else None
        steady = steady + 1 if current and current == last else 0
        last = current
        time.sleep(0.05)


def _restore(hwnd: int) -> None:
    _settle(hwnd)
    try:
        left, top, right, bottom = json.loads(WINDOW_STATE.read_text(encoding="utf-8"))
        saved = _on_screen(left, top, right, bottom)
    except (OSError, ValueError):
        saved = False
    for _ in range(3):
        if saved:
            _user32.SetWindowPos(hwnd, None, left, top, right - left, bottom - top, SWP_NOZORDER)
            target = (left, top, right, bottom)
        else:
            _place_default(hwnd)
            target = _rect(hwnd)
        time.sleep(0.15)
        if _rect(hwnd) == target:
            return


def _bring_to_front(hwnd: int) -> None:
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, SW_RESTORE)
    _user32.SetForegroundWindow(hwnd)
    _remember(hwnd)


def show_window() -> None:
    """有 Friday 窗口就拿到最前面，没有就开一个。"""
    hwnd = find_window()
    if hwnd:
        _bring_to_front(hwnd)
        return
    browser = _app_browser()
    if not browser:
        webbrowser.open(URL)
        return
    _user32.AllowSetForegroundWindow(ASFW_ANY)
    subprocess.Popen(
        [browser, f"--app={URL}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS,
    )
    deadline = time.monotonic() + 5
    while not (hwnd := find_window()) and time.monotonic() < deadline:
        time.sleep(0.05)
    if hwnd:
        _restore(hwnd)
        _bring_to_front(hwnd)


def toggle_window() -> None:
    """快捷键的行为：Friday 在最前面就收起，否则叫出来。"""
    hwnd = find_window()
    if hwnd and _user32.GetForegroundWindow() == hwnd:
        _remember(hwnd)
        _user32.ShowWindow(hwnd, SW_MINIMIZE)
        return
    show_window()


def listen_hotkey(on_press: Callable[[], None]) -> bool:
    """在本线程注册 Ctrl+Alt+F 并一直等它；组合键已被别人占用就返回 False。"""
    if not _user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("F")):
        return False
    msg = wt.MSG()
    while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            on_press()
    return True
