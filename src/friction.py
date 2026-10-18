"""产品摩擦：他嫌弃过的建议/打扰，记下来，下一轮照着避开。改代码以后再 mark 关掉。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.config import DATA_DIR

FRICTION_PATH = DATA_DIR / "feedback" / "friction.jsonl"
INJECT_LIMIT = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_all() -> list[dict[str, Any]]:
    if not FRICTION_PATH.is_file():
        return []
    items: list[dict[str, Any]] = []
    for line in FRICTION_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("id") and row.get("what"):
            items.append(row)
    return items


def _append(row: dict[str, Any]) -> None:
    FRICTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FRICTION_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rewrite(items: list[dict[str, Any]]) -> None:
    FRICTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRICTION_PATH.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in items),
        encoding="utf-8",
    )


def note(what: str, better: str = "") -> dict[str, Any]:
    """记下一条他还在意的摩擦。"""
    text = (what or "").strip()
    if not text:
        return {"ok": False, "error": "empty", "message": "没有可记的内容。"}
    row = {
        "id": uuid4().hex[:10],
        "what": text,
        "better": (better or "").strip(),
        "status": "open",
        "at": _now(),
    }
    _append(row)
    return {"ok": True, "id": row["id"], "say": "记下了，下次按这个来。"}


def open_items(limit: int = 20) -> list[dict[str, Any]]:
    items = [x for x in _read_all() if x.get("status") == "open"]
    items.reverse()  # 新的在前
    return items[: max(1, min(limit, 50))]


def resolve(friction_id: str) -> dict[str, Any]:
    fid = (friction_id or "").strip()
    if not fid:
        return {"ok": False, "error": "missing_id", "message": "缺少 id。"}
    items = _read_all()
    found = False
    for row in items:
        if row.get("id") == fid and row.get("status") == "open":
            row["status"] = "resolved"
            row["resolved_at"] = _now()
            found = True
            break
    if not found:
        return {"ok": False, "error": "not_found", "message": "没有这条未改的摩擦。"}
    _rewrite(items)
    return {"ok": True, "id": fid, "say": "这条划掉了。"}


def chat_block() -> str:
    """每轮注入：他还嫌弃、没改掉的；照着避开，别辩护。"""
    items = open_items(INJECT_LIMIT)
    if not items:
        return ""
    lines = []
    for row in items:
        line = f"- [{row['id']}] {row['what']}"
        if row.get("better"):
            line += f"（更好：{row['better']}）"
        lines.append(line)
    return "他还嫌弃、没改掉的（照着避开，别辩护；别复述整段清单）：\n" + "\n".join(lines)
