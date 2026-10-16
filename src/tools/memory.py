"""长期记忆工具：写入 / 检索 / 删除本地事实。"""

from __future__ import annotations

from typing import Any

from agents import function_tool

from src import memory_store


@function_tool
def remember_fact(content: str, tags: str = "") -> dict[str, Any]:
    """把关于用户的事实或偏好写入长期记忆（本地）。

    当用户说「记住…」「以后用…」时调用。不要写入敏感密码。

    Args:
        content: 要记住的事实（一句话，完整可检索）。
        tags: 可选标签，逗号或空格分隔，如 fyp,mentor,email。
    """
    return memory_store.remember_fact(content=content, tags=tags)


@function_tool
def search_memory(query: str, top: int = 5) -> dict[str, Any]:
    """按关键词检索长期记忆中的事实。

    在个性化回答、准备会议、需要导师邮箱/偏好等时先检索，不要编造。

    Args:
        query: 检索词，如 mentor email、FYP、偏好。
        top: 返回条数，默认 5。
    """
    return memory_store.search_facts(query=query, top=top)


@function_tool
def forget_fact(fact_id: str, user_confirmed: bool = False) -> dict[str, Any]:
    """删除一条长期记忆。必须先 request_user_confirmation，用户同意后
    以 user_confirmed=True 调用。

    Args:
        fact_id: search_memory 返回的 id。
        user_confirmed: 用户是否已确认删除。
    """
    if not user_confirmed:
        return {
            "ok": False,
            "error": "user_not_confirmed",
            "message": (
                "删除记忆需要确认。请先 request_user_confirmation，"
                "同意后再以 user_confirmed=True 调用。"
            ),
        }
    return memory_store.forget_fact(fact_id)
