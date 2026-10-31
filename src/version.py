"""Friday 的版本号，和服务端代码的指纹。

VERSION 是给人看的版本号（MAJOR.MINOR.PATCH），只在这里写一次：资料页、/api/health、CHANGELOG.md 都跟着它。
- 多了一样他能交给 Friday 的事（新能力、新的一块界面）→ MINOR +1，PATCH 归零
- 修好、调顺、改措辞，但他用起来有变化 → PATCH +1
- 只改文档或测试 → 不动
- 1.0.0 = 周二测试通过（连续一个普通周期主动打开它）：那时合进 main、打 tag v1.0.0

改 VERSION 的同一个提交里，在 CHANGELOG.md 最上面加这一版（测试会核对两边一致）。

code_version() 是另一回事：代码或 .env 一变就变的指纹，启动器靠它判断要不要换新进程。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

VERSION = "0.9.0"

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
