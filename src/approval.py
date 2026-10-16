"""Autonomy / approval policy（薄层，无外部权限系统）。"""

from __future__ import annotations

from typing import Literal

# 工具级默认策略：当前实现的工具都是只读 → allow
# 未来写操作工具应登记为 require_confirmation
ToolPolicy = Literal["allow", "require_confirmation"]

TOOL_POLICIES: dict[str, ToolPolicy] = {
    "get_calendar_events": "allow",
    "search_files": "allow",
    "read_file": "allow",
    "search_emails": "allow",
    "read_email": "allow",
    "get_personal_context": "allow",
    "request_user_confirmation": "allow",
    "create_calendar_event": "require_confirmation",
}

WRITE_ACTION_TYPES = {
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
    "send_email",
    "share_file",
    "other_write",
}


def policy_for_tool(tool_name: str) -> ToolPolicy:
    return TOOL_POLICIES.get(tool_name, "require_confirmation")


def requires_confirmation(action_type: str) -> bool:
    return action_type in WRITE_ACTION_TYPES or action_type.startswith("write_")
