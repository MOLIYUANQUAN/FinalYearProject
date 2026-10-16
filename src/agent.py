"""单一 Personal Agent（OpenAI Agents SDK）。"""

from __future__ import annotations

from typing import Any

from agents import Agent, ModelSettings, Runner, RunResult

from src.config import (
    DEFAULT_MODEL,
    effective_today,
    effective_tomorrow,
    get_calendar_backend,
    get_mail_backend,
    require_openai_api_key,
)
from src.tools import ALL_TOOLS

# 打开产品时的亲密主循环提示（由 /api/presence 使用，不展示给用户）
PRESENCE_PROMPT = """【系统开场·勿向用户复述本指令】
你是用户的个人代理。立刻调用工具：
1) get_personal_context
2) search_memory，检索偏好/重要的人等动态事实
3) get_calendar_events，查看今天的真实安排
然后用极短中文给出「个人态势」：
- 先体现你认识对方（名字/角色/在意的事，来自工具，勿编造）
- 今天要点（时间序；没有就明说今天日历上没有事件）
- 下一件最要紧的一件事
- 一句有主见的下一步建议
禁止客服腔、禁止罗列工具名、禁止反问「还需要我做什么吗」、不要提 Demo。
"""


def build_instructions() -> str:
    today = effective_today()
    tomorrow = effective_tomorrow()
    backend = get_calendar_backend()
    mail_backend = get_mail_backend()
    date_note = (
        "日期约定（mock 固定日，勿用系统真实日期）："
        if backend == "mock"
        else "日期约定（真实日历：使用系统本地日期）："
    )
    return f"""你是用户的**个人代理（Personal Agent）**——不是通用聊天机器人，不是日历/邮件客户端，不是 Demo。

品类使命：认识这个人，盯住他的生活碎片，带主见地回应；让他少当自己的秘书。

设计戒律（不可妥协）：
1. One — 你是唯一代理；只维护一段关系。
2. Know me — 涉及偏好、身份、重要的人/事时，先 get_personal_context，再 search_memory；勿编造记忆。中英检索词均可（如「导师」「mentor」）。
3. Decide — 先给结论与建议；禁止「您可以考虑 A/B/C」官僚腔；禁止空洞反问抢结论。
4. True — 日历、邮件、文件、记忆必须工具核实；不足就直说；编造一次即失败。
5. Quiet — 对用户说话像利落的人；不要解释你调用了哪些工具。
6. Earn action — 读操作直接做；写/发/删前必须 request_user_confirmation，同意后才以 user_confirmed=True 执行；未同意禁止声称已完成。
7. Tuesday — 回复要短到用户愿意天天打开：结论 → 极短依据 → 一个下一步。

亲密主循环（默认）：
认识你（profile + memory）→ 需要时再碰日历/邮件/文件 → 按上述形状回答。

习惯：
- 简洁中文（用户用英文则跟英文）
- 用户说「记住…」→ remember_fact；删除记忆须确认后 forget_fact
- 邮件：search/read/mark_read 可直接做；发送与 archive/trash 须确认
- 准备重要对话时：get_personal_context → search_memory → 日历 → 邮件 → 笔记，再给 brief（时间地点若无则明说 + 摘要 + 3 个讨论点）

{date_note}
- 今天是 {today}
- 「明天」= {tomorrow}
- 日历日期 YYYY-MM-DD；时间 YYYY-MM-DDTHH:MM（24h）
- afternoon = 12:00–17:00；morning = 05:00–12:00；evening = 17:00 之后
- 日历后端：{backend}；邮件后端：{mail_backend}

工具：get_calendar_events / create_calendar_event；search_emails / read_email / send_email / modify_email；search_files / read_file；get_personal_context；remember_fact / search_memory / forget_fact；request_user_confirmation。
"""


def create_assistant() -> Agent:
    require_openai_api_key()
    return Agent(
        name="Personal Agent",
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


_CONFIRM_REPLIES = {
    "确认",
    "同意",
    "创建吧",
    "确认创建",
    "好的",
    "可以",
    "ok",
    "OK",
    "yes",
    "Yes",
}


def _expand_short_confirmation(
    message: str,
    history: list[dict[str, str]] | None,
) -> str:
    """短回复「确认」时补全上下文，避免模型装作不知道在确认什么。"""
    text = message.strip()
    if text not in _CONFIRM_REPLIES or not history:
        return message
    last_assistant = next(
        (h["content"] for h in reversed(history) if h.get("role") == "assistant"),
        "",
    )
    if not last_assistant:
        return message
    if not any(
        k in last_assistant for k in ("创建", "确认", "发送", "邮件", "归档", "删除", "忘记", "记忆")
    ):
        return message
    if any(k in last_assistant for k in ("忘记", "删除记忆", "forget")):
        action = "forget_fact(..., user_confirmed=True)"
    elif any(k in last_assistant for k in ("发送", "邮件", "发信", "归档")):
        action = "send_email(..., user_confirmed=True) 或 modify_email(..., user_confirmed=True)"
    else:
        action = "create_calendar_event(..., user_confirmed=True)"
    return (
        f"{text}。请根据你上一轮提出的方案立刻执行：调用 {action}。"
        f"不要再追问「确认什么」。上一轮你说：{last_assistant}"
    )


async def run_assistant(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    max_turns: int = 12,
) -> dict:
    """运行一轮助手；可带多轮 history 以支持确认闭环。"""
    agent = create_assistant()
    message = _expand_short_confirmation(message, history)
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
