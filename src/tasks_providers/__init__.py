"""待办来源：none | mock | google。没接入时没有来源，卡片和对话里都不出现待办。"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from src.config import get_tasks_backend


class TasksProvider(Protocol):
    """每条待办：id、title、due（YYYY-MM-DD 或 None）、notes。"""

    name: str

    def list_open(self) -> list[dict[str, Any]]: ...

    def add(self, title: str, due: date | None, notes: str | None) -> dict[str, Any]: ...

    def set_due(self, task_id: str, due: date | None) -> dict[str, Any]: ...

    def complete(self, task_id: str) -> dict[str, Any]: ...

    def reopen(self, task_id: str) -> dict[str, Any]: ...

    def delete(self, task_id: str) -> None: ...


def get_tasks_provider() -> TasksProvider | None:
    backend = get_tasks_backend()
    if backend == "google":
        from src.tasks_providers.google_tasks import GoogleTasksProvider

        return GoogleTasksProvider()
    if backend == "mock":
        from src.tasks_providers.mock import MockTasksProvider

        return MockTasksProvider()
    return None


__all__ = ["TasksProvider", "get_tasks_provider"]
