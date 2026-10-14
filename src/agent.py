"""单一 Personal Assistant Agent（OpenAI Agents SDK）。"""

from __future__ import annotations

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

{date_note}
- 今天是 {today}
- 「明天」= {tomorrow}
- 调用 get_calendar_events 时，date 必须传 YYYY-MM-DD（例如明天 → {tomorrow}）
- afternoon = 12:00–17:00；morning = 05:00–12:00；evening = 17:00 之后
- 当前日历后端：{backend}

可用工具：
- get_calendar_events：查日历（mock 或 Google）
- search_files：在本地笔记中搜索
- read_file：读取笔记全文

准备会议时：先查日历确认时间/地点/备注，再搜索并阅读相关提案或笔记，最后输出 meeting brief（时间地点、目的、项目摘要、建议讨论点）。
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
    """从 RunResult 提取本轮调用过的工具名（去重保序）。"""
    names: list[str] = []
    for item in result.new_items:
        name = getattr(item, "tool_name", None)
        if not name and getattr(item, "type", None) == "tool_call_item":
            raw = getattr(item, "raw_item", None)
            name = getattr(raw, "name", None) if raw is not None else None
        if name and name not in names:
            names.append(str(name))
    return names


async def run_assistant(message: str, *, max_turns: int = 8) -> dict:
    """运行一轮助手，返回回复与工具调用列表。"""
    agent = create_assistant()
    result = await Runner.run(agent, message, max_turns=max_turns)
    reply = result.final_output
    if not isinstance(reply, str):
        reply = str(reply)
    return {
        "reply": reply,
        "tools_called": extract_tool_names(result),
    }
