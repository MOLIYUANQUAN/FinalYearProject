#!/usr/bin/env python3
"""装好 Friday 的入口：桌面 + 开始菜单快捷方式，以及开机后常驻后台（服务就绪 + Ctrl+Alt+F）。

  python scripts/install_shortcuts.py           # 安装 / 更新，并立刻开始常驻
  python scripts/install_shortcuts.py --remove  # 全部移除，并停掉常驻
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from open_agent import RESIDENT_PID, stop_resident

ROOT = Path(__file__).resolve().parent.parent
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
LAUNCHER = ROOT / "scripts" / "open_agent.py"
ICON = ROOT / "static" / "friday-ring.ico"
NAME = "Friday.lnk"
DETACHED_PROCESS = 0x00000008


def _quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _powershell(lines: list[str]) -> str:
    # 逐行从 stdin 喂给 PowerShell：不落 .ps1 文件，也不用编码命令
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", "-"],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0 or result.stderr.strip():
        sys.exit(result.stderr.strip() or f"powershell exited {result.returncode}")
    return result.stdout.strip()


FOLDERS = [
    "$desktop = [Environment]::GetFolderPath('Desktop')",
    "$programs = [Environment]::GetFolderPath('Programs')",
    "$startup = [Environment]::GetFolderPath('Startup')",
]


def install() -> None:
    if not PYTHONW.is_file():
        sys.exit(f"missing {PYTHONW}; create the venv first")
    # 快捷键由常驻进程自己监听：Explorer 的快捷方式热键每次都要等好几秒
    make = (
        "$make = { param($path, $arguments) "
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($path); "
        f"$s.TargetPath = {_quote(PYTHONW)}; "
        "$s.Arguments = $arguments; "
        f"$s.WorkingDirectory = {_quote(ROOT)}; "
        f"$s.IconLocation = {_quote(str(ICON) + ',0')}; "
        "$s.Description = 'Friday'; "
        "$s.Hotkey = ''; "
        "$s.Save(); $path }"
    )
    launcher = f'"{LAUNCHER}"'
    out = _powershell(
        [
            *FOLDERS,
            make,
            f"& $make (Join-Path $desktop '{NAME}') {_quote(launcher)}",
            f"& $make (Join-Path $programs '{NAME}') {_quote(launcher)}",
            f"& $make (Join-Path $startup '{NAME}') {_quote(launcher + ' --resident')}",
        ]
    )
    print(out)
    stop_resident()
    subprocess.Popen(
        [str(PYTHONW), str(LAUNCHER), "--resident"],
        cwd=ROOT,
        creationflags=DETACHED_PROCESS,
    )
    print("Friday: desktop + Start menu shortcuts; resident in the background with Ctrl+Alt+F.")
    print(f"(resident pid file: {RESIDENT_PID})")


def remove() -> None:
    stop_resident()
    out = _powershell(
        [
            *FOLDERS,
            "foreach ($dir in @($desktop, $programs, $startup)) { "
            f"$p = Join-Path $dir '{NAME}'; "
            "if (Test-Path $p) { Remove-Item $p; \"removed $p\" } }",
        ]
    )
    print(out or "nothing to remove")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Friday shortcuts")
    parser.add_argument("--remove", action="store_true", help="remove all Friday shortcuts")
    args = parser.parse_args()
    remove() if args.remove else install()


if __name__ == "__main__":
    main()
