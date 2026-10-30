"""待办工具：一句话记下、一句话划掉。直接做，不用先问：页面会给他「撤销」。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from agents import RunContextWrapper, function_tool

from src import closed, todos
from src.config import effective_now
from src.tasks_providers import get_tasks_provider
from src.turn import Turn

NOT_CONNECTED = {"ok": False, "error": "not_connected", "message": "待办还没接入。"}


def _reason(exc: Exception) -> str:
    return str(exc).splitlines()[0] if isinstance(exc, RuntimeError) else "这次没连上待办。"


def _offer_undo(ctx: RunContextWrapper[Any], item: dict[str, Any]) -> None:
    if isinstance(ctx.context, Turn):
        ctx.context.undo.append(item)


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text).casefold()


@function_tool
def add_task(ctx: RunContextWrapper[Any], title: str, due: str = "", notes: str = "") -> dict[str, Any]:
    """把他交代的一件要做完的事放进待办（Google Tasks）。同名的已经在清单里就不重复记；他改了截止日就改日子。

    Args:
        title: 要做的事，短短一句，用他的说法（「Lab 3」「交房租」），不带「记得」「提醒我」和日子；改日子时用清单里那件的名字。
        due: 截止的日子，照他的原话传（「今天」「周四」「下周一」「10月22日」），或 YYYY-MM-DD；他没说就留空。
        notes: 可选补充，比如具体钟点（「下午 5 点前」）或链接。
    """
    provider = get_tasks_provider()
    if provider is None:
        return NOT_CONNECTED
    today = effective_now().date()
    due_day = todos.parse_due(due, today) if due.strip() else None
    if due.strip() and due_day is None:
        return {"ok": False, "error": "due_unclear", "message": f"「{due}」是哪天没看懂：换成 YYYY-MM-DD 再调用一次。"}

    def when(day: date | None) -> str:
        return f"，{todos.when_due(day, today)}截止" if day else ""

    try:
        tasks, _ = todos.read(60)
        same = next((t for t in tasks if _norm(t["title"]) == _norm(title)), None)
        if same and (due_day is None or todos.due_date(same) == due_day):
            return {"ok": True, "title": same["title"], "say": f"已经记着了：{same['title']}{when(todos.due_date(same))}。"}
        if same:
            task = provider.set_due(same["id"], due_day)
            undo, said = {"kind": "task_due_changed", "due": same["due"]}, "改好了"
        else:
            task = provider.add(title.strip(), due_day, notes.strip() or None)
            undo, said = {"kind": "task_added"}, "记下了"
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "add_failed", "message": _reason(exc)}
    todos.forget()
    _offer_undo(ctx, {**undo, "id": task["id"], "title": task["title"]})
    return {"ok": True, "title": task["title"], "say": f"{said}：{task['title']}{when(due_day)}。"}


@function_tool
def complete_task(ctx: RunContextWrapper[Any], which: str) -> dict[str, Any]:
    """划掉一件做完的待办。

    Args:
        which: 是哪一件，用他的说法或清单里的名字（「Lab 3」）。
    """
    provider = get_tasks_provider()
    if provider is None:
        return NOT_CONNECTED
    try:
        tasks, _ = todos.read(60)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "read_failed", "message": _reason(exc)}
    key = _norm(which)
    exact = [t for t in tasks if _norm(t["title"]) == key]
    matches = exact or [t for t in tasks if key and (key in _norm(t["title"]) or _norm(t["title"]) in key)]
    if not matches:
        return {"ok": False, "error": "not_found", "open": [t["title"] for t in tasks]}
    if len(matches) > 1:
        return {"ok": False, "error": "ambiguous", "candidates": [t["title"] for t in matches]}
    try:
        task = provider.complete(matches[0]["id"])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "complete_failed", "message": _reason(exc)}
    todos.forget()
    closed.record("task", task["title"], ref=f"task:{task['id']}")
    _offer_undo(ctx, {"kind": "task_completed", "id": task["id"], "title": task["title"]})
    return {"ok": True, "title": task["title"], "say": f"划掉了：{task['title']}。"}
