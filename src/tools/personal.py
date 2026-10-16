"""个人上下文工具：读取本地 profile（非长期 memory DB）。"""

from __future__ import annotations

from typing import Any

from agents import function_tool

from src.config import PROFILE_PATH


@function_tool
def get_personal_context() -> dict[str, Any]:
    """读取用户的个人偏好与上下文（本地 profile）。

    在需要按用户习惯个性化回答、准备会议、或判断是否该先确认时调用。
    不要编造 profile 中没有的信息。
    """
    if not PROFILE_PATH.is_file():
        return {
            "ok": False,
            "path": str(PROFILE_PATH),
            "error": "personal profile not found",
            "content": "",
        }
    content = PROFILE_PATH.read_text(encoding="utf-8")
    return {
        "ok": True,
        "path": str(PROFILE_PATH.relative_to(PROFILE_PATH.parents[1])),
        "content": content,
    }
