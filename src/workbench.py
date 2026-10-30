"""开工台上点一下就办：做完了、明天再说。不经过模型，结果也记进对话（换设备看得到，她也知道）。

「帮我准备」不在这里：那是交给 Friday 去办的事，页面直接发一句话给她。
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src import closed, engineering, ship, todos
from src.agent import friday
from src.config import effective_now
from src.tasks_providers import get_tasks_provider

router = APIRouter(tags=["workbench"])


class ActBody(BaseModel):
    key: str = Field(..., max_length=200, description="卡片那一行的 key，例如 task:abc")
    action: str = Field(..., pattern="^(done|tomorrow|preview|ship)$")
    conversation_id: str | None = Field(None, max_length=64)


def _task(task_id: str) -> tuple[Any, dict[str, Any]]:
    provider = get_tasks_provider()
    if provider is None:
        raise HTTPException(status_code=400, detail="待办还没接入。")
    tasks, _ = todos.read(30)
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="这件已经不在清单里了。")
    return provider, task


async def _record(conversation_id: str | None, say: str, undo: list[dict[str, Any]] | None = None) -> dict:
    """点一下办完的事也记进对话：换设备看得到，她也知道刚发生了什么。"""
    cid = friday.resolve_conversation(conversation_id)
    message_id = friday.conversations.add_message(cid, "assistant", say, undo=undo or [], tools=[])
    await friday.conversations.session(cid).add_items([{"role": "assistant", "content": say}])
    return {"ok": True, "say": say, "undo": undo or [], "message_id": message_id, "conversation_id": cid}


async def _ship_action(body: ActBody) -> dict:
    """「看改动」直接给文件列表和说明；「上线」是他在卡片上亲手点的（点了两次），等同确认。"""
    pending = ship.load_or_recover_pending()
    if not pending:
        raise HTTPException(status_code=404, detail="现在没有待上线的改动。")
    if body.action == "preview":
        return await _record(body.conversation_id, ship.preview_text(pending))
    summary = pending.get("summary") or pending.get("branch") or ""
    result = await asyncio.to_thread(ship.ship, user_confirmed=True)
    engineering.forget()
    if result.get("merged") or result.get("ok"):
        engineering.record_shipped(summary)
        closed.record("ship", summary.splitlines()[0] if summary else "上线了一版")
    say = result.get("say") or result.get("message") or ("已合进 develop，正在上线。" if result.get("ok") else "没上成。")
    return await _record(body.conversation_id, say)


@router.post("/api/items/act")
async def act(body: ActBody) -> dict:
    kind, _, item_id = body.key.partition(":")
    if body.key == "ship:pending" and body.action in {"preview", "ship"}:
        return await _ship_action(body)
    if kind != "task" or not item_id or body.action not in {"done", "tomorrow"}:
        raise HTTPException(status_code=400, detail="这一行不能这样办。")
    provider, task = _task(item_id)
    try:
        if body.action == "done":
            provider.complete(task["id"])
            closed.record("task", task["title"], ref=f"task:{task['id']}")
            undo = {"kind": "task_completed", "id": task["id"], "title": task["title"]}
            say = f"划掉了：{task['title']}。"
        else:
            tomorrow = effective_now().date() + timedelta(days=1)
            provider.set_due(task["id"], tomorrow)
            undo = {"kind": "task_due_changed", "id": task["id"], "title": task["title"], "due": task.get("due")}
            say = f"改到明天了：{task['title']}。"
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).splitlines()[0] if isinstance(exc, RuntimeError) else "待办这次没连上"
        raise HTTPException(status_code=502, detail=f"没办成：{reason}") from exc
    finally:
        todos.forget()

    return await _record(body.conversation_id, say, [undo])
