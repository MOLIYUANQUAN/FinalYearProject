"""服务端代码的指纹：代码或 .env 变了，启动器才换新进程；没变就直接用正在跑的。"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def code_version() -> str:
    files = sorted((ROOT / "src").rglob("*.py"))
    env = ROOT / ".env"
    if env.is_file():
        files.append(env)
    digest = hashlib.sha1()
    for path in files:
        stat = path.stat()
        digest.update(f"{path.relative_to(ROOT)}|{stat.st_mtime_ns}|{stat.st_size}\n".encode())
    return digest.hexdigest()[:12]
