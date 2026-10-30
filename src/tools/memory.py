"""长期记忆工具：写入 / 检索 / 删除本地事实。"""

from __future__ import annotations

from typing import Any

from agents import function_tool

from src import memory_store


@function_tool
def remember_fact(content: str, tags: str = "", replaces: str = "") -> dict[str, Any]:
    """把关于他的长期事实或偏好写入记忆（只存本机）。

    他说「记住…」、或顺带说出关于自己的长期事实/偏好时调用。
    他纠正一条已有记忆时，用 replaces 传旧记忆的 id，新事实直接替换旧的（纠正不需要确认）。
    不要写入密码、一次性的事、或你自己的推测。
    要去做的事（「记得买牛奶」「提醒我交房租」）不是关于他的事实，不用这个工具：有 add_task 就用 add_task。

    Args:
        content: 一句完整的事实，脱离上下文也能看懂。
        tags: 可选标签，逗号分隔，如 fyp,mentor。
        replaces: 被纠正的旧记忆 id（「你记得的事」里方括号中的 id）；不是纠正就留空。
    """
    return memory_store.remember_fact(content=content, tags=tags, replaces=replaces)


@function_tool
def search_memory(query: str, top: int = 5) -> dict[str, Any]:
    """在更早的记忆里按关键词检索。最近的记忆已经在你的上下文里，只有那里找不到时才用。

    Args:
        query: 检索词，中英文均可，如 导师、mentor email、FYP、偏好。
        top: 返回条数，默认 5。
    """
    return memory_store.search_facts(query=query, top=top)


@function_tool(needs_approval=True)
def forget_fact(fact_id: str) -> dict[str, Any]:
    """删除一条长期记忆（系统会先请他确认）。纠正记忆请用 remember_fact(replaces=...)，不要用这个。

    Args:
        fact_id: 记忆 id。
    """
    return memory_store.forget_fact(fact_id)
