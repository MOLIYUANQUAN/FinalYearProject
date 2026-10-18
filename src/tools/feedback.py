"""产品摩擦工具：记下不好用的建议，列出来，改掉后划掉；确认后可叫 Cursor 改代码。"""

from __future__ import annotations

from typing import Any

from agents import function_tool

from src import cursor_fix, friction


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
    说清要改什么、会动仓库；他点确认后以 user_confirmed=True 调用。可能要几分钟。

    有 friction_id 就修那条；没有就用 what 当场记下再修。不要为了「流程正式」再多问一轮。

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
    return cursor_fix.run_fix(fid)
