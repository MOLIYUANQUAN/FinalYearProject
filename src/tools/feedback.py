"""产品摩擦工具：记下不好用的建议，列出来，改掉后划掉；确认后可叫 Cursor 改代码。"""

from __future__ import annotations

from typing import Any

from agents import function_tool

from src import cursor_fix, friction, ship


@function_tool
def note_friction(what: str, better: str = "") -> dict[str, Any]:
    """记下他对 Friday 产品/建议/打扰方式的不满，供以后改和下一轮避开。

    他抱怨「这个建议不好」「别再这样催我」「我不想看见明天的事一直摆着」时调用。
    不要把关于他自己的长期事实记到这里——那用 remember_fact。

    Args:
        what: 一句完整的摩擦，脱离上下文也能看懂，例如「不要把明天的会放进需要你里一直催」。
        better: 可选，他希望怎样，例如「明天只出现在日程分区，不进需要你」。
    """
    return friction.note(what=what, better=better)


@function_tool
def list_friction(top: int = 10) -> dict[str, Any]:
    """列出他还嫌弃、没改掉的产品摩擦。

    他问「我说过哪些不好用」「待修清单」时调用。

    Args:
        top: 返回条数，默认 10。
    """
    items = friction.open_items(top)
    return {
        "ok": True,
        "count": len(items),
        "items": [{"id": x["id"], "what": x["what"], "better": x.get("better") or ""} for x in items],
    }


@function_tool
def resolve_friction(friction_id: str) -> dict[str, Any]:
    """把一条产品摩擦标成已改掉。他确认「这条修好了」或改完代码后调用。不需要先确认。

    Args:
        friction_id: list_friction / 上下文里方括号中的 id。
    """
    return friction.resolve(friction_id)


@function_tool
def fix_friction_with_cursor(
    friction_id: str = "",
    what: str = "",
    better: str = "",
    user_confirmed: bool = False,
) -> dict[str, Any]:
    """用 Cursor Agent 改 Friday 的代码。必须先 request_user_confirmation（只问一次），
    说清要改什么、会动仓库；他点确认后以 user_confirmed=True 调用。

    工具会立刻返回「已交给 Cursor」，不要干等几分钟。有 friction_id 就修那条；
    没有就用 what 当场记下再修。

    Args:
        friction_id: 已有摩擦 id（可选）。
        what: 没有 id 时必填：要改成什么样，一句说清。
        better: 可选，更具体的期望。
        user_confirmed: 用户是否已确认让 Cursor 改代码。
    """
    fid = (friction_id or "").strip()
    text = (what or "").strip()
    item = next((x for x in friction.open_items(50) if x.get("id") == fid), None) if fid else None
    label = (item or {}).get("what") or text or fid or "改代码"
    if not user_confirmed:
        return {
            "ok": False,
            "error": "user_not_confirmed",
            "message": (
                "还没确认。请先 request_user_confirmation，说明要用 Cursor 修："
                f"「{label}」，同意后再以 user_confirmed=True 调用同一参数。"
            ),
        }
    if item is None:
        if not text:
            return {
                "ok": False,
                "error": "missing_what",
                "message": "没有摩擦 id，也没有 what。用他刚才说的改动目标填 what，再调用一次。",
            }
        created = friction.note(what=text, better=better)
        if not created.get("ok"):
            return created
        fid = str(created["id"])
    return cursor_fix.start_fix(fid)


@function_tool
def check_cursor_fix() -> dict[str, Any]:
    """查 Cursor 改代码进度：还在跑 / 改完待部署 / 失败。

    他问「改好了吗」「Cursor 好了吗」「进度」时调用。把返回的 say 原样告诉他；
    若已 ready，可再 preview_pending_ship 看文件列表。
    """
    return cursor_fix.check_status()


@function_tool
def preview_pending_ship() -> dict[str, Any]:
    """查看 Cursor 改完、还没部署的那一版：改了哪些文件、说明是什么。

    他问「改了什么」「效果怎么样」「待部署」时调用。把返回的 say 原样给他看。
    """
    cursor_fix.refresh_job()
    pending = ship.load_or_recover_pending()
    if not pending:
        job = cursor_fix.check_status()
        if job.get("status") == "running":
            return {"ok": False, "error": "still_running", "say": job.get("say") or "还在改。"}
        return {"ok": False, "error": "nothing_pending", "say": "现在没有待部署的改动。"}
    refreshed = ship.save_pending(
        branch=pending["branch"],
        summary=pending.get("summary") or "",
        agent_id=pending.get("agent_id") or "",
        run_id=pending.get("run_id") or "",
        friction_id=pending.get("friction_id") or "",
        agent_url=pending.get("agent_url") or "",
    )
    cursor_fix.acknowledge_delivered()
    return {"ok": True, "say": refreshed["say"], "files": refreshed.get("files") or []}


@function_tool
def ship_pending_fix(user_confirmed: bool = False) -> dict[str, Any]:
    """把待部署的 Cursor 改动合进 develop 并部署到云上。必须先确认一次。

    他把「确认部署」或点确认后，以 user_confirmed=True 调用。把返回的 say 原样告诉他。

    Args:
        user_confirmed: 用户是否已确认合并并部署。
    """
    return ship.ship(user_confirmed=user_confirmed)
