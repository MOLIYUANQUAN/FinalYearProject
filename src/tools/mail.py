"""邮件工具：Gmail / mock / outlook（outlook 仍只读）。"""

from __future__ import annotations

from typing import Any, Literal

from agents import function_tool

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


@function_tool
def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    user_confirmed: bool = False,
) -> dict[str, Any]:
    """发送一封新邮件。必须先 request_user_confirmation，用户明确同意后
    才能以 user_confirmed=True 调用。

    Args:
        to: 收件人邮箱。
        subject: 主题。
        body: 正文（纯文本）。
        cc: 可选抄送，逗号分隔。
        user_confirmed: 用户是否已确认发送。
    """
    if not user_confirmed:
        return {
            "ok": False,
            "error": "user_not_confirmed",
            "message": (
                "尚未获得用户确认。请先 request_user_confirmation，"
                "展示收件人/主题/正文摘要，待同意后再以 user_confirmed=True 调用。"
            ),
        }
    provider = get_mail_provider()
    send = getattr(provider, "send_message", None)
    if send is None:
        return {"ok": False, "error": "send_not_supported", "source": provider.name}
    try:
        return send(to=to, subject=subject, body=body, cc=cc)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "send_failed", "message": str(exc)}


@function_tool
def modify_email(
    message_id: str,
    action: ModifyAction,
    user_confirmed: bool = False,
) -> dict[str, Any]:
    """修改邮件状态：标记已读/未读、归档、移到垃圾桶。

    mark_read / mark_unread 可直接执行；archive / trash 必须先确认且 user_confirmed=True。

    Args:
        message_id: 邮件 ID。
        action: mark_read | mark_unread | archive | trash
        user_confirmed: archive/trash 时必须为 True。
    """
    if action in {"archive", "trash"} and not user_confirmed:
        return {
            "ok": False,
            "error": "user_not_confirmed",
            "message": (
                f"动作 {action} 需要确认。请先 request_user_confirmation，"
                "同意后再以 user_confirmed=True 调用。"
            ),
        }

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
