"""邮件工具：Gmail / mock / outlook（outlook 仍只读）。"""

from __future__ import annotations

from typing import Any, Literal

from agents import function_tool

from src.approval import mail_change_needs_approval
from src.mail_providers import get_mail_provider

ModifyAction = Literal["mark_read", "mark_unread", "archive", "trash"]


@function_tool
def search_emails(query: str = "", top: int = 5) -> dict[str, Any]:
    """搜索或列出最近邮件。

    Args:
        query: 关键词（如 FYP、mentor）。空字符串表示收件箱最近邮件。
        top: 返回条数，默认 5，最大 20。
    """
    return get_mail_provider().search_messages(query=query, top=top)


@function_tool
def read_email(message_id: str) -> dict[str, Any]:
    """读取一封邮件全文。message_id 来自 search_emails。

    Args:
        message_id: 邮件 ID。
    """
    return get_mail_provider().get_message(message_id)


@function_tool(needs_approval=True)
def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
) -> dict[str, Any]:
    """发送一封新邮件。直接调用：系统会先把收件人、主题和正文给他看，他确认后才真的发。

    Args:
        to: 收件人邮箱。
        subject: 主题。
        body: 正文（纯文本）。
        cc: 可选抄送，逗号分隔。
    """
    provider = get_mail_provider()
    send = getattr(provider, "send_message", None)
    if send is None:
        return {"ok": False, "error": "send_not_supported", "source": provider.name}
    try:
        return send(to=to, subject=subject, body=body, cc=cc)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "send_failed", "message": str(exc)}


@function_tool(needs_approval=mail_change_needs_approval)
def modify_email(
    message_id: str,
    action: ModifyAction,
) -> dict[str, Any]:
    """修改邮件状态：标记已读/未读、归档、移到垃圾桶。

    mark_read / mark_unread 直接执行；archive / trash 系统会先请他确认。

    Args:
        message_id: 邮件 ID。
        action: mark_read | mark_unread | archive | trash
    """
    add: list[str] = []
    remove: list[str] = []
    if action == "mark_read":
        remove = ["UNREAD"]
    elif action == "mark_unread":
        add = ["UNREAD"]
    elif action == "archive":
        remove = ["INBOX"]
    elif action == "trash":
        add = ["TRASH"]
        remove = ["INBOX"]
    else:
        return {"ok": False, "error": "unknown_action", "action": action}

    provider = get_mail_provider()
    modify = getattr(provider, "modify_labels", None)
    if modify is None:
        return {"ok": False, "error": "modify_not_supported", "source": provider.name}
    try:
        result = modify(
            message_id=message_id,
            add_labels=add,
            remove_labels=remove,
        )
        if isinstance(result, dict):
            result["action"] = action
        return result
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "modify_failed", "message": str(exc)}
