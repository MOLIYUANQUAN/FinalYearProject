"""单一 Personal Assistant Agent（OpenAI Agents SDK）。"""

from __future__ import annotations

from typing import Any

from agents import Agent, ModelSettings, Runner, RunResult

from src.config import (
    DEFAULT_MODEL,
    effective_today,
    effective_tomorrow,
    get_calendar_backend,
    require_openai_api_key,
)
from src.tools import ALL_TOOLS


def build_instructions() -> str:
    today = effective_today()
    tomorrow = effective_tomorrow()
    backend = get_calendar_backend()
    date_note = (
        "日期约定（mock 演示固定日，勿用系统真实日期）："
        if backend == "mock"
        else "日期约定（真实日历：使用系统本地日期）："
    )
    return f"""你是用户的单一个人 AI 助手（Personal Assistant）。

规则：
1. 有日历或本地文件相关问题时，必须调用工具核实，不要编造日程或文件内容。
2. 可以串联多次工具调用：先查日历，再搜索/读取相关文件，最后综合回答。
3. 工具结果不足时如实说明，不要假装知道。
4. 用简洁中文回复（除非用户用英文提问）。
5. 需要按用户习惯个性化时，先调用 get_personal_context。
6. 创建/修改日历等写操作流程（必须遵守）：
   a) 先 request_user_confirmation，说明标题与起止时间；
   b) 等待用户在对话中明确同意（如「确认」「同意」「创建吧」）；
   c) 仅在同意后调用 create_calendar_event(..., user_confirmed=True)；
   d) 用户未同意前，禁止 user_confirmed=True，也禁止声称已创建。

{date_note}
- 今天是 {today}
- 「明天」= {tomorrow}
- 调用日历工具时，日期用 YYYY-MM-DD；时间用 YYYY-MM-DDTHH:MM（24小时制）
- afternoon = 12:00–17:00；morning = 05:00–12:00；evening = 17:00 之后
- 当前日历后端：{backend}

可用工具：
- get_calendar_events：查日历
- create_calendar_event：创建事件（需先确认）
- search_files / read_file：本地笔记
- get_personal_context：个人偏好
- request_user_confirmation：写操作前请求确认

准备会议时：按需 get_personal_context → 查日历 → 读相关文件 → 输出 meeting brief。
"""


def create_assistant() -> Agent:
    require_openai_api_key()
    return Agent(
        name="Personal Assistant",
        instructions=build_instructions(),
        tools=ALL_TOOLS,
        model=DEFAULT_MODEL,
        model_settings=ModelSettings(temperature=0.2),
    )


def extract_tool_names(result: RunResult) -> list[str]:
    names: list[str] = []
    for item in result.new_items:
        name = getattr(item, "tool_name", None)
        if not name and getattr(item, "type", None) == "tool_call_item":
            raw = getattr(item, "raw_item", None)
            name = getattr(raw, "name", None) if raw is not None else None
        if name and name not in names:
            names.append(str(name))
    return names


def _history_to_input(
    message: str,
    history: list[dict[str, str]] | None,
) -> str | list[dict[str, Any]]:
    """把多轮历史打成 Agents SDK 可接受的 input。"""
    if not history:
        return message
    items: list[dict[str, Any]] = []
    for turn in history:
        role = (turn.get("role") or "").strip()
        content = (turn.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        items.append({"role": role, "content": content})
    items.append({"role": "user", "content": message})
    return items


async def run_assistant(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    max_turns: int = 12,
) -> dict:
    """运行一轮助手；可带多轮 history 以支持确认闭环。"""
    agent = create_assistant()
    result = await Runner.run(
        agent,
        _history_to_input(message, history),
        max_turns=max_turns,
    )
    reply = result.final_output
    if not isinstance(reply, str):
        reply = str(reply)
    return {
        "reply": reply,
        "tools_called": extract_tool_names(result),
    }
