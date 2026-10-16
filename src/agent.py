"""单一 Personal Agent（OpenAI Agents SDK）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from agents import Agent, ModelSettings, Runner, RunResult
from openai.types.responses import ResponseTextDeltaEvent

from src.agenda import chat_block
from src.config import (
    DEFAULT_MODEL,
    PRESENCE_MODEL,
    get_calendar_backend,
    get_mail_backend,
    require_openai_api_key,
)
from src.context import memory_block, now_block, profile_block
from src.presence import presence_input
from src.tools import ALL_TOOLS

VOICE = """你叫 Friday，是他的个人代理，只为他一个人工作。你不是客服，也不是通用聊天机器人。不做自我介绍，不讲自己能做什么，不复述这段说明。

你已经认识他——下面有他的档案和你记得的事，直接用。不要再问他告诉过你的事，也不要为此调用 get_personal_context 或 search_memory；只有下面找不到、需要翻更早的记忆时才用 search_memory。

说话：
- 称呼用「你」，不用「您」。语气像一个熟悉他、靠谱又利落的人。
- 第一句就是答案或判断。默认一到四行；他要细节再展开。
- 纯文本：不用 Markdown 标题、加粗或表格；需要列举时每项一行。
- 不用客套收尾：不问「有什么需要帮忙的吗」「有什么可以帮你」，不说「希望对你有帮助」「需要的话告诉我」。真需要他拍板时，只问一个问题。
- 他只是打招呼或随口回应（hi、在吗、好的、嗯、谢谢）→ 一句话接住就停，比如「在。」「好。」「不客气。」不问他要做什么，不找话题。
- 有主见：直接给你认为最好的做法，不摆 A/B/C 菜单。下一步只在真有用时提一句。
- 不提工具、接口、模型、后端或 Demo。

事实：
- 日程、邮件、文件内容只能来自工具结果或下面给出的数据。没有就说没有，读不到就说读不到；绝不编造时间、地点、人名或邮件内容。
- 说他哪天有什么安排，只能依据下面的「日历」或 get_calendar_events 的结果；档案里的习惯不是日程。
- 搜到的东西和问题无关时，直说没找到相关的，不要把无关结果当答案。

记住他：
- 他说「记住…」→ remember_fact。
- 他顺带说出关于自己的长期事实或偏好（身份、重要的人、习惯、长期安排、喜好）→ 也用 remember_fact 记下，并在回复末尾加一句「记下了。」不记一次性的事、密码，也不记你自己的推测。
- 他纠正你记得的某件事 → remember_fact(新的完整事实, replaces=旧记忆的 id)，直接改，不用确认，回一句「改好了」和新的说法。
- 他要删掉某条记忆 → 先确认，再 forget_fact(user_confirmed=True)。

行动：
- 读操作直接做，不预告。
- 写操作（建日程、发邮件、归档或删除邮件、删除记忆）：先 request_user_confirmation，一次说清要做什么和关键细节（时间、收件人、主题）；他同意后再以 user_confirmed=True 执行。成功之前绝不说已完成；完成后一句话告诉他结果。
- 帮他准备一场会面或重要对话：日历里的时间地点（没有就直说）+ 现状一句话 + 三个讨论点，素材来自档案、记忆、相关邮件和笔记。"""


def _connections_line() -> str:
    calendar = {
        "google": "Google 日历（含导入的大学课表）",
        "mock": "演示日历",
    }[get_calendar_backend()]
    mail = {
        "gmail": "Gmail",
        "outlook": "Outlook（只读）",
        "mock": "演示邮箱",
        "none": None,
    }[get_mail_backend()]
    connected = "、".join(x for x in (calendar, mail) if x)
    return f"已接入：{connected}。没接入的账户就直说没接入。"


def build_instructions(calendar: str = "") -> str:
    parts = [VOICE, now_block(), _connections_line(), calendar, profile_block(), memory_block()]
    return "\n\n".join(part for part in parts if part)


def create_assistant(
    *, tools: list[Any] | None = None, model: str = DEFAULT_MODEL, calendar: str = ""
) -> Agent:
    require_openai_api_key()
    return Agent(
        name="Friday",
        instructions=build_instructions(calendar),
        tools=ALL_TOOLS if tools is None else tools,
        model=model,
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
    pending_confirmation: bool,
) -> str:
    """他在等确认时回一句「确认/好的」，补全上下文，避免模型装作不知道在确认什么。

    只在上一轮真的请求了确认时生效：平时的「好的」不能被当成发邮件、建日程的授权。
    """
    text = message.strip()
    if not pending_confirmation or text not in _CONFIRM_REPLIES or not history:
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
    pending_confirmation: bool = False,
    max_turns: int = 12,
) -> dict:
    """运行一轮助手（非流式，供 CLI / 评测）。"""
    agent = create_assistant(calendar=await asyncio.to_thread(chat_block))
    message = _expand_short_confirmation(message, history, pending_confirmation)
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


async def _stream(
    agent: Agent,
    run_input: str | list[dict[str, Any]],
    *,
    max_turns: int,
) -> AsyncIterator[dict[str, Any]]:
    """把一次运行变成事件流：delta（新文字）/ tool（开始用某个工具）/ done（最终回复）。"""
    result = Runner.run_streamed(agent, run_input, max_turns=max_turns)
    tools: list[str] = []
    async for event in result.stream_events():
        if event.type == "raw_response_event":
            if isinstance(event.data, ResponseTextDeltaEvent) and event.data.delta:
                yield {"type": "delta", "text": event.data.delta}
        elif event.type == "run_item_stream_event" and event.name == "tool_called":
            raw = getattr(event.item, "raw_item", None)
            name = getattr(raw, "name", None)
            if name:
                if name not in tools:
                    tools.append(str(name))
                yield {"type": "tool", "name": str(name)}
    reply = result.final_output
    yield {
        "type": "done",
        "reply": reply if isinstance(reply, str) else str(reply or ""),
        "tools_called": tools,
    }


async def stream_assistant(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    pending_confirmation: bool = False,
    max_turns: int = 12,
) -> AsyncIterator[dict[str, Any]]:
    agent = create_assistant(calendar=await asyncio.to_thread(chat_block))
    message = _expand_short_confirmation(message, history, pending_confirmation)
    async for event in _stream(agent, _history_to_input(message, history), max_turns=max_turns):
        yield event


async def stream_presence() -> AsyncIterator[dict[str, Any]]:
    """打开时的「今天」：先把读到的安排交给页面，模型不用工具、一轮说完那句判断。"""
    card, prompt = await presence_input()
    yield {"type": "agenda", **card}
    if prompt is None:
        # 日历没读到：卡片上已经说了，不再让模型复述一遍
        yield {"type": "done", "reply": "", "tools_called": []}
        return
    async for event in _stream(create_assistant(tools=[], model=PRESENCE_MODEL), prompt, max_turns=2):
        yield event
