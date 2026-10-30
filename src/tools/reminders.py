"""提醒工具：到点由 Friday 推送叫他。几点由服务端从他的原话算，回复一字不改照说。"""

from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from src import push, reminders
from src.config import effective_now
from src.turn import Turn


def _offer_undo(ctx: RunContextWrapper[Any], item: dict[str, Any]) -> None:
    if isinstance(ctx.context, Turn):
        ctx.context.undo.append(item)


@function_tool
def remind_me(ctx: RunContextWrapper[Any], what: str, when: str) -> dict[str, Any]:
    """到点由 Friday 推送叫他（精确到分钟）。他说了具体钟点或「N 分钟后」就用这个。

    Args:
        what: 要提醒他的事，用他的说法，短短一句（「给妈妈打电话」），不带「提醒我」和时间。
        when: 什么时候，照他的原话传（「下午三点」「20分钟后」「明早8点」「周五晚上8点」），不要自己换算。
    """
    now = effective_now()
    at = reminders.parse_when(when, now)
    if at is None:
        return {"ok": False, "error": "when_unclear", "message": f"「{when}」是几点没看懂，或者那个时间已经过了：问他一句是几点。"}
    item = reminders.add(what, at)
    _offer_undo(ctx, {"kind": "reminder_added", "id": item["id"], "title": item["what"]})
    say = f"好，{reminders.said_when(at, now)}叫你：{item['what']}。"
    if not push.devices():
        say += "不过你还没打开提醒，到点我没法找你：在开场卡片下面点「打开提醒」。"
    return {"ok": True, "say": say}


@function_tool
def cancel_reminder(ctx: RunContextWrapper[Any], which: str) -> dict[str, Any]:
    """取消一个还没到点的提醒。

    Args:
        which: 是哪一个，用他的说法（「给妈妈打电话那个」）。
    """
    matches = reminders.find(which)
    if not matches:
        return {"ok": False, "error": "not_found", "pending": [r["what"] for r in reminders.pending()]}
    if len(matches) > 1:
        return {"ok": False, "error": "ambiguous", "candidates": [r["what"] for r in matches]}
    item = reminders.cancel(matches[0]["id"])
    _offer_undo(ctx, {"kind": "reminder_cancelled", "id": item["id"], "title": item["what"]})
    return {"ok": True, "say": f"不提醒了：{item['what']}。"}
