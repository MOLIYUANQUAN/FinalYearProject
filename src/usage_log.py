"""本地使用记录：只记元数据、不记对话内容，用来回答「他是不是真的每天在用」。"""

from __future__ import annotations

import json
from datetime import datetime

from src.config import USAGE_LOG_PATH


def parse(line: str) -> dict | None:
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return None
    return row if isinstance(row, dict) else None


def record(
    kind: str,
    *,
    ok: bool,
    first_token_ms: int | None,
    total_ms: int,
    tools: list[str],
) -> None:
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "ok": ok,
        "first_token_ms": first_token_ms,
        "total_ms": total_ms,
        "tools": tools,
    }
    try:
        USAGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
