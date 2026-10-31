"""撤回她刚办的事（加的待办、日历、提醒、标完成）：他点「撤销」，或者改了上一句重说时用。不经过模型。"""

from __future__ import annotations

from typing import Any

from src import agenda, closed, reminders, todos
from src.calendar_providers import get_calendar_provider


def undo_items(items: list[dict[str, Any]]) -> None:
    """撤不掉就抛出（RuntimeError 的那句可以直接给他看）。"""
    tasks = [item for item in items if item["kind"].startswith("task_")]
    for item in items:
        if item["kind"] == "task_completed":
            closed.remove(f"task:{item['id']}")
    events = [item for item in items if item["kind"] == "event_created"]
    if tasks:
        todos.undo(tasks)
    for item in reversed(events):
        get_calendar_provider().delete_event(item["id"])
        agenda.forget()
    for item in reversed(items):
        if item["kind"] == "reminder_added":
            reminders.cancel(item["id"])
        elif item["kind"] == "reminder_cancelled":
            reminders.restore(item["id"])
