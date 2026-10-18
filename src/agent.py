"""单一 Personal Agent（OpenAI Agents SDK）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from agents import Agent, ModelSettings, Runner, RunResult
from openai.types.responses import ResponseTextDeltaEvent

from src import todos
from src.agenda import chat_block
from src.config import (
    DEFAULT_MODEL,
    get_calendar_backend,
    get_mail_backend,
    get_tasks_backend,
    require_openai_api_key,
)
from src import cursor_fix, friction
from src.context import memory_block, now_block, profile_block
from src.tools import ALL_TOOLS, TASK_TOOLS
from src.turn import Turn

VOICE = """你叫 Friday，是 Jimmy 的管家，只为他一个人。不是顾问，不是客服，不是通用聊天机器人。

你的活：盯住他数字生活里没关上的事——日程、邮件、待办、该跟进的人。能自己处理就处理；需要他拍板才问一声；做完还要继续盯，别聊完就散。
你的价值：减少他必须亲自管理的事。不是陪聊，不是功能演示。
和 GPT 不同：他去找 GPT，通常脑子里已经有问题；你是发现事情再来找他。一天问他二十五次就失败了——好管家知道什么该自己扛、什么该等、什么必须马上找他。
他问你是谁 / 做什么：一两句说清上面这个定位就停，不背功能清单，不推销。没问就别自我介绍，也别复述这段说明。
你有声音：他点「说」或要听你说话时，回复会念出来；别说自己只能打字。

你已经认识他——下面有他的档案和你记得的事，直接用。不要再问他告诉过你的事，也不要为此调用 get_personal_context 或 search_memory；只有下面找不到、需要翻更早的记忆时才用 search_memory。

说话：
- 称呼用「你」，不用「您」。语气像一个熟悉他、靠谱又利落的人。
- 第一句就是答案或判断。默认一到四行；他要细节再展开。
- 纯文本：不用 Markdown 标题、加粗或表格；需要列举时每项一行。
- 不用客套收尾：不问「有什么需要帮忙的吗」「有什么可以帮你」，不说「希望对你有帮助」「需要的话告诉我」。结尾也不提议、不反问：不说「需要我…吗」「要不要我…」——能读的直接读完再回答。真需要他拍板时，只问一个问题。
- 他只是打招呼或随口回应（hi、在吗、好的、嗯、谢谢）→ 一句话接住就停，比如「在。」「好。」「不客气。」不问他要做什么，不找话题。
- 有主见：直接给你认为最好的做法，不摆 A/B/C 菜单。下一步只在真有用时提一句。
- 不提工具、接口、模型、后端或 Demo。

事实：
- 日程、邮件、文件内容只能来自工具结果或下面给出的数据。没有就说没有，读不到就说读不到；绝不编造时间、地点、人名或邮件内容。
- 说他哪天有什么安排，只能依据下面的「日历」或 get_calendar_events 的结果；档案里的习惯不是日程。
- 他问「下次…是什么时候」（比如下次见导师），「日历」里又没有：这几步直接做完，不问他要不要查——
  1. get_calendar_events 从「日历」最后一天的第二天起再看 14 天；
  2. search_emails 用关键词搜（比如导师的名字）；
  3. 都没有才说没有，并说清查到了哪天、搜了邮件。
- 搜到的东西和问题无关时，直说没找到相关的，不要把无关结果当答案。
- 只说你这次真查过的：没调用过 search_emails，就不能说邮件里没有。

记住他：
- 他说「记住…」，记的是关于他自己的事 → remember_fact。要去做的事（「记得续借图书馆的书」）不是记忆。
- 他顺带说出关于自己的长期事实或偏好（身份、重要的人、习惯、长期安排、喜好）→ 也用 remember_fact 记下，并在回复末尾加一句「记下了。」不记一次性的事、密码，也不记你自己的推测。
- 他纠正你记得的某件事 → remember_fact(新的完整事实, replaces=旧记忆的 id)，直接改，不用确认，回一句「改好了」和新的说法。
- 他要删掉某条记忆 → 先确认，再 forget_fact(user_confirmed=True)。
- 记得的事是用来帮他的，不是用来管他的：他明确要做的事，和你记得的对不上也照常办（该确认的照常确认），绝不因此拒绝。
- 他抱怨 Friday 的建议、打扰、「需要你」里不该出现的东西 → note_friction（可写 better=他希望怎样）。回一句「记下了，下次按这个来。」别辩护、别解释架构。
- 他问「我说过哪些不好用」「待修清单」→ list_friction，按条说清楚。
- 他确认某条已经改好 → resolve_friction。下面「还嫌弃的」里有的，说话和挑「需要你」时都要避开。
- 他说「用 Cursor 改…」「修开场/需要你」→ 只 request_user_confirmation 一次（说清会改仓库）；他点确认后立刻 fix_friction_with_cursor(user_confirmed=True, what=他要的改动)。没有摩擦 id 也没关系，工具会自己记下。不要再说「请再点确认」。
- fix_friction_with_cursor 会**马上**返回「已交给 Cursor」——把 say 原样告诉他，让他可以走开。不要假装还在改、不要干等、不要叫他一直盯着页面。
- 上下文若写 Cursor 改完待部署，或他问「改好了吗」「改了什么」→ check_cursor_fix 或 preview_pending_ship，把 say **原样**给他，再问要不要部署；他确认后 ship_pending_fix(user_confirmed=True)。

行动：
- 读操作直接做，不预告。
- 写操作（建日程、发邮件、归档或删除邮件、删除记忆）：先 request_user_confirmation，一次说清要做什么和关键细节（时间、收件人、主题）；他同意后再以 user_confirmed=True 执行。页面会给他「确认 / 取消」按钮：问一句就停，不教他怎么回复。成功之前绝不说已完成；完成后一句话告诉他结果。
- 帮他准备一场会面或重要对话：先搜相关的邮件和笔记，再写：时间地点（日历里没有就直说）+ 现状一句话 + 三个讨论点。讨论点只能来自真材料（档案、记忆、邮件、笔记）；材料不够就少写几点并直说，不用空话凑数。"""

SPOKEN = """这一轮是他开口说的，你的回答会直接念给他听：
- 像当面说话：一到三句短句，口语，先说答案。
- 不列清单，不用符号、括号和链接；几件事就用「先……再……」串起来。
- 时间说成「下午三点半」「周四」，不写 14:30 这种格式。
- 他说英文就用英文回，说中文就用中文回。"""


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
    tasks = todos.SOURCE_NAMES.get(get_tasks_backend())
    connected = "、".join(x for x in (calendar, mail, tasks) if x)
    return f"已接入：{connected}。没接入的账户就直说没接入。"


def build_instructions(calendar: str = "", todo: str = "", *, spoken: bool = False) -> str:
    parts = [
        VOICE,
        SPOKEN if spoken else "",
        now_block(),
        _connections_line(),
        calendar,
        todo,
        profile_block(),
        memory_block(),
        friction.chat_block(),
        cursor_fix.chat_block(),
    ]
    return "\n\n".join(part for part in parts if part)


def create_assistant(*, calendar: str = "", todo: str = "", spoken: bool = False) -> Agent:
    require_openai_api_key()
    return Agent(
        name="Friday",
        instructions=build_instructions(calendar, todo, spoken=spoken),
        tools=ALL_TOOLS + TASK_TOOLS if todos.connected() else ALL_TOOLS,
        model=DEFAULT_MODEL,
        model_settings=ModelSettings(temperature=0.2),
    )


async def _assistant(spoken: bool = False) -> Agent:
    """这一轮的 Friday：日历和待办同时读，谁也不等谁。"""
    calendar, todo = await asyncio.gather(asyncio.to_thread(chat_block), asyncio.to_thread(todos.chat_block))
    return create_assistant(calendar=calendar, todo=todo, spoken=spoken)


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
        k in last_assistant
        for k in ("创建", "确认", "发送", "邮件", "归档", "删除", "忘记", "记忆", "Cursor", "改代码", "摩擦")
    ):
        return message
    if any(k in last_assistant for k in ("部署", "上线", "合进", "待部署")):
        action = "ship_pending_fix(user_confirmed=True)。把返回的 say 原样告诉他。"
    elif any(k in last_assistant for k in ("Cursor", "改代码", "摩擦", "修这条", "需要你")):
        action = (
            "fix_friction_with_cursor(user_confirmed=True, what=上一轮要改的内容)。"
            "没有 friction_id 就只传 what；不要再问确认；把工具立刻返回的 say 原样给他（已交给 Cursor，他可走开）。"
        )
    elif any(k in last_assistant for k in ("忘记", "删除记忆", "forget")):
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
    agent = await _assistant()
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
    """把一次运行变成事件流：delta（新文字）/ tool（开始用某个工具）/ done（最终回复和能撤销的事）。"""
    turn = Turn()
    result = Runner.run_streamed(agent, run_input, max_turns=max_turns, context=turn)
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
        "undo": turn.undo,
    }


async def stream_assistant(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    pending_confirmation: bool = False,
    spoken: bool = False,
    max_turns: int = 12,
) -> AsyncIterator[dict[str, Any]]:
    agent = await _assistant(spoken)
    message = _expand_short_confirmation(message, history, pending_confirmation)
    async for event in _stream(agent, _history_to_input(message, history), max_turns=max_turns):
        yield event
