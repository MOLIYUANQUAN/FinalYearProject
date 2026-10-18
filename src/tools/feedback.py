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
def fix_friction_with_cursor(friction_id: str, user_confirmed: bool = False) -> dict[str, Any]:
    """用 Cursor Agent 按一条产品摩擦改 Friday 的代码。必须先 request_user_confirmation，
    说清要修哪一条、会改仓库；他同意后再以 user_confirmed=True 调用。可能要几分钟。

    Args:
        friction_id: list_friction / 上下文里方括号中的 id。
        user_confirmed: 用户是否已确认让 Cursor 改代码。
    """
    if not user_confirmed:
        item = next((x for x in friction.open_items(50) if x.get("id") == (friction_id or "").strip()), None)
        what = item["what"] if item else friction_id
        return {
            "ok": False,
            "error": "user_not_confirmed",
            "message": (
                "还没确认。请先 request_user_confirmation，说明要用 Cursor 修："
                f"「{what}」，同意后再以 user_confirmed=True 调用。"
            ),
        }
    return cursor_fix.run_fix(friction_id)
