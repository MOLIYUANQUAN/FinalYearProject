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
    "modify_email": "require_confirmation",  # archive/trash 工具内再细分
    "get_personal_context": "allow",
    "remember_fact": "allow",
    "search_memory": "allow",
    "forget_fact": "require_confirmation",
    "note_friction": "allow",
    "list_friction": "allow",
    "resolve_friction": "allow",
    "fix_friction_with_cursor": "require_confirmation",
    "check_cursor_fix": "allow",
    "preview_pending_ship": "allow",
    "ship_pending_fix": "require_confirmation",
    "request_user_confirmation": "allow",
    "create_calendar_event": "require_confirmation",
    "send_email": "require_confirmation",
    # 待办只进他自己的清单、随时能撤回：直接做，页面给「撤销」
    "add_task": "allow",
    "complete_task": "allow",
}

WRITE_ACTION_TYPES = {
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
    "send_email",
    "modify_email",
    "archive_email",
    "trash_email",
    "forget_fact",
    "fix_friction_with_cursor",
    "ship_pending_fix",
    "share_file",
    "other_write",
}


def policy_for_tool(tool_name: str) -> ToolPolicy:
    return TOOL_POLICIES.get(tool_name, "require_confirmation")


def requires_confirmation(action_type: str) -> bool:
    return action_type in WRITE_ACTION_TYPES or action_type.startswith("write_")
