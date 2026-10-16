"""用户确认工具：写操作前必须先请求确认（本阶段不执行写操作）。"""

from __future__ import annotations

from typing import Any, Literal

from agents import function_tool

from src.approval import WRITE_ACTION_TYPES, requires_confirmation

ActionType = Literal[
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
    "send_email",
    "share_file",
    "other_write",
]


@function_tool
def request_user_confirmation(
    action_type: ActionType,
    summary: str,
    details: str = "",
) -> dict[str, Any]:
    """在执行任何写操作/对外发送之前，先向用户请求确认。

    本阶段系统不会真正执行写操作。调用本工具后，你必须把确认请求展示给用户，
    并等待用户明确同意；在同意前不得声称操作已完成。

    Args:
        action_type: 动作类型（创建/修改日程、发邮件等）。
        summary: 一句话说明要做什么。
        details: 可选细节（时间、收件人、内容草稿等）。
    """
    needed = requires_confirmation(action_type)
    return {
        "status": "confirmation_required" if needed else "not_required",
        "action_type": action_type,
        "summary": summary,
        "details": details,
        "known_write_actions": sorted(WRITE_ACTION_TYPES),
        "message": (
            "请向用户展示此确认请求，并等待明确同意。"
            if needed
            else "该动作不需要确认。"
        ),
    }
