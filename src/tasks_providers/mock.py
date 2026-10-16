"""演示待办：从 data/tasks.json 起步；改动只留在内存里，演示和实测都不会改文件。"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import date
from typing import Any

from src.config import TASKS_PATH

_lock = threading.Lock()
_tasks: dict[str, dict[str, Any]] | None = None


def _store() -> dict[str, dict[str, Any]]:
    global _tasks
    if _tasks is None:
        raw = json.loads(TASKS_PATH.read_text(encoding="utf-8")) if TASKS_PATH.is_file() else {}
        _tasks = {t["id"]: {**t, "done": False} for t in raw.get("tasks") or []}
    return _tasks


def _public(task: dict[str, Any]) -> dict[str, Any]:
    return {key: task.get(key) for key in ("id", "title", "due", "notes")}


class MockTasksProvider:
    name = "mock"

    def list_open(self) -> list[dict[str, Any]]:
        with _lock:
            return [_public(t) for t in _store().values() if not t["done"]]

    def add(self, title: str, due: date | None, notes: str | None) -> dict[str, Any]:
        task = {
            "id": f"task-{uuid.uuid4().hex[:8]}",
            "title": title,
            "due": due.isoformat() if due else None,
            "notes": notes,
            "done": False,
        }
        with _lock:
            _store()[task["id"]] = task
        return _public(task)

    def set_due(self, task_id: str, due: date | None) -> dict[str, Any]:
        return self._change(task_id, due=due.isoformat() if due else None)

    def complete(self, task_id: str) -> dict[str, Any]:
        return self._change(task_id, done=True)

    def reopen(self, task_id: str) -> dict[str, Any]:
        return self._change(task_id, done=False)

    def delete(self, task_id: str) -> None:
        with _lock:
            _store().pop(task_id, None)

    def _change(self, task_id: str, **fields: Any) -> dict[str, Any]:
        with _lock:
            task = _store().get(task_id)
            if task is None:
                raise RuntimeError("这条待办已经不在了。")
            task.update(fields)
            return _public(task)
