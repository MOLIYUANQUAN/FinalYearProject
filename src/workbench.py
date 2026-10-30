"""开工台上点一下就办：做完了、明天再说。不经过模型，结果也记进对话（换设备看得到，她也知道）。

「帮我准备」不在这里：那是交给 Friday 去办的事，页面直接发一句话给她。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src import todos
from src.agent import friday
from src.config import effective_now
from src.tasks_providers import get_tasks_provider

router = APIRouter(tags=["workbench"])


class ActBody(BaseModel):
    key: str = Field(..., max_length=200, description="卡片那一行的 key，例如 task:abc")
    action: str = Field(..., pattern="^(done|tomorrow)$")
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


@router.post("/api/items/act")
async def act(body: ActBody) -> dict:
    kind, _, item_id = body.key.partition(":")
    if kind != "task" or not item_id:
        raise HTTPException(status_code=400, detail="这一行不能这样办。")
    provider, task = _task(item_id)
    try:
        if body.action == "done":
            provider.complete(task["id"])
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

    cid = friday.resolve_conversation(body.conversation_id)
    message_id = friday.conversations.add_message(cid, "assistant", say, undo=[undo], tools=[])
    await friday.conversations.session(cid).add_items([{"role": "assistant", "content": say}])
    return {"ok": True, "say": say, "undo": [undo], "message_id": message_id, "conversation_id": cid}
