"""替他关掉了哪些事：划掉的待办、发出的邮件、上线的改动。收工小结和每周那句「这周关掉了 N 件」从这里数。

只记 Friday 经手的；撤销了就从账上划掉。存在 STATE_DIR/closed.jsonl。
"""

from __future__ import annotations

import json
import threading
from datetime import date, timedelta
from typing import Any

from src import usage_log
from src.config import STATE_DIR, effective_now

CLOSED_PATH = STATE_DIR / "closed.jsonl"
_lock = threading.Lock()


def _read() -> list[dict[str, Any]]:
    if not CLOSED_PATH.is_file():
        return []
    rows = []
    for line in CLOSED_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def record(kind: str, title: str, ref: str = "") -> None:
    now = effective_now()
    row = {"day": now.date().isoformat(), "at": now.strftime("%Y-%m-%dT%H:%M"), "kind": kind, "title": title, "ref": ref}
    with _lock:
        CLOSED_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CLOSED_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    usage_log.record("closed", ok=True, first_token_ms=None, total_ms=0, tools=[kind])


def remove(ref: str) -> None:
    """撤销了：这件不算关掉。"""
    if not ref:
        return
    with _lock:
        rows = _read()
        kept = [r for r in rows if r.get("ref") != ref]
        if len(kept) != len(rows):
            CLOSED_PATH.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")


def on_day(day: date) -> list[dict[str, Any]]:
    return [r for r in _read() if r.get("day") == day.isoformat()]


def in_week(day: date) -> list[dict[str, Any]]:
    """那一周（周一到周日）关掉的。"""
    monday = day - timedelta(days=day.weekday())
    days = {(monday + timedelta(days=i)).isoformat() for i in range(7)}
    return [r for r in _read() if r.get("day") in days]
