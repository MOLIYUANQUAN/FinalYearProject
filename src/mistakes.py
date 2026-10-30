"""她说错的话：他点「说错了」就记一条（他问的、她答的、用了哪些工具），之后补成一条测试。

目标是「说错的次数：0」——先得数得出来。usage_report 里那一列「说错」就来自这里。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.config import FEEDBACK_DIR

MISTAKES_PATH = FEEDBACK_DIR / "mistakes.jsonl"


def record(*, asked: str, said: str, tools: list[str], opener: bool = False, note: str = "") -> dict[str, Any]:
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asked": asked,
        "said": said,
        "tools": tools,
        "opener": opener,
        "note": note.strip(),
    }
    MISTAKES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MISTAKES_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def all_items() -> list[dict[str, Any]]:
    if not MISTAKES_PATH.is_file():
        return []
    items = []
    for line in MISTAKES_PATH.read_text(encoding="utf-8").splitlines():
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items
