#!/usr/bin/env python3
"""把本机 Friday 临时开到公网，让 iPhone Safari 打开同一个对话。

需要：Friday 服务在跑（8765）、本机装了 cloudflared。
会确保 .env 里有 FRIDAY_ACCESS_TOKEN，并打印带访问码的链接。
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import get_access_token, load_env  # noqa: E402

ENV_PATH = ROOT / ".env"
PORT = 8765
URL_RE = re.compile(r"https?://[a-zA-Z0-9.-]+\.(trycloudflare\.com|cfargotunnel\.com)")


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def _ensure_token() -> str:
    load_env()
    token = get_access_token()
    if token:
        return token
    token = secrets.token_urlsafe(18)
    line = f"\n# Phone access (scripts/phone_access.py)\nFRIDAY_ACCESS_TOKEN={token}\n"
    with ENV_PATH.open("a", encoding="utf-8") as f:
        f.write(line)
    # 清掉已加载的旧值，下次 get_access_token 会重新读
    os.environ["FRIDAY_ACCESS_TOKEN"] = token
    print(f"Wrote FRIDAY_ACCESS_TOKEN into {ENV_PATH}")
    return token


def _health(token: str) -> bool:
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/health")
    req.add_header("Authorization", f"Bearer {token}")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _ensure_server(token: str) -> None:
    # 必须重启：刚写入的访问码要被进程读进内存；旧进程可能还是「不设码」
    print("Restarting Friday on 8765 so the access token is loaded…")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "open_agent.py"), "--no-window", "--restart"],
        cwd=ROOT,
        check=False,
    )
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if _health(token):
            return
        time.sleep(0.4)
    _fail("Friday 没起来。先双击 Friday.cmd，再跑这个脚本。看 data\\logs\\server.err.log。")


def _cloudflared() -> str:
    found = shutil.which("cloudflared")
    if found:
        return found
    local = ROOT / "tools" / "cloudflared.exe"
    if local.is_file():
        return str(local)
    _fail(
        "没找到 cloudflared。\n"
        "1) 打开 https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/\n"
        "2) 下载 Windows 版，放到 PATH，或放到 D:\\FYP\\tools\\cloudflared.exe\n"
        "3) 再运行：.venv\\Scripts\\python.exe scripts\\phone_access.py"
    )


def main() -> None:
    if not ENV_PATH.is_file():
        _fail(f"缺少 {ENV_PATH}：先复制 .env.example 并填好 OPENAI_API_KEY。")
    token = _ensure_token()
    _ensure_server(token)
    exe = _cloudflared()
    print("Tunnel starting. Keep this window open. Ctrl+C stops the tunnel (Friday itself keeps running).")
    print("Waiting for public URL…")
    proc = subprocess.Popen(
        [exe, "tunnel", "--url", f"http://127.0.0.1:{PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    assert proc.stdout is not None
    public = None
    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            match = URL_RE.search(line)
            if match and public is None:
                public = match.group(0).rstrip("/")
                link = f"{public}/?access={token}"
                print()
                print("=" * 60)
                print("On your iPhone Safari, open:")
                print(link)
                print()
                print("Optional: Share → Add to Home Screen")
                print("Same Friday as Ctrl+Alt+F. Do not post this link.")
                print("=" * 60)
                print()
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("\nTunnel stopped.")


if __name__ == "__main__":
    main()
