"""邮件工具：mock 或 Outlook（Microsoft Graph）只读。"""

from __future__ import annotations

from typing import Any

from agents import function_tool

from src.mail_providers import get_mail_provider


@function_tool
def search_emails(query: str = "", top: int = 5) -> dict[str, Any]:
    """搜索或列出最近邮件（只读）。

    Args:
        query: 关键词（如 FYP、mentor、课程代码）。空字符串表示最近邮件。
        top: 返回条数，默认 5，最大 20。
    """
    provider = get_mail_provider()
    return provider.search_messages(query=query, top=top)


@function_tool
def read_email(message_id: str) -> dict[str, Any]:
    """读取一封邮件全文（只读）。message_id 来自 search_emails 的结果。

    Args:
        message_id: 邮件 ID。
    """
    provider = get_mail_provider()
    return provider.get_message(message_id)
