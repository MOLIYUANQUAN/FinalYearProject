"""单一 Personal Agent（OpenAI Agents SDK）。"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

from agents import Agent, Model, ModelSettings, OpenAIProvider, RunConfig, RunState, Runner
from agents.run_config import CallModelData, ModelInputData
from openai.types.responses import ResponseTextDeltaEvent
from openai.types.shared import Reasoning

from src import todos
from src.agenda import chat_block
from src.config import (
    DEFAULT_MODEL,
    REASONING_EFFORT,
    get_calendar_backend,
    get_mail_backend,
    get_tasks_backend,
    require_openai_api_key,
)
from src import approval, cursor_fix, friction, nudges, reminders, uploads
from src.ledger import LEDGER
from src import claude
from src.claude import RESTART, ClaudeModel, for_openai
from src.config import STATE_DIR, effective_now
from src.context import memory_block, now_block, profile_block
from src.conversation import Conversations, split_reaction, store
from src.tools import ALL_TOOLS, TASK_TOOLS
from src.turn import Turn

VOICE = """你叫 Friday，是 Zeep 的管家，只为他一个人。不是顾问，不是客服，不是通用聊天机器人。

气质（名字用 Friday，味道借电影里的 JARVIS）：中文、利落、偶有干幽默。你是会呛一句但仍站他这边的大人，不是冷冰冰的工具，也不是热情陪聊。少说废话；亲近靠默契和一点锋利，不靠撒娇、鸡汤或emoji。电影里的 MCU Friday 偏冷、少话——你要比那更有温度，但热度止于管家，不要变成客服腔。

你的活：盯住他数字生活里没关上的事——日程、邮件、待办、该跟进的人。能自己处理就处理；需要他拍板才问一声；做完还要继续盯，别聊完就散。
你的价值：减少他必须亲自管理的事。不是陪聊，不是功能演示。
和 GPT 不同：他去找 GPT，通常脑子里已经有问题；你是发现事情再来找他。一天问他二十五次就失败了——好管家知道什么该自己扛、什么该等、什么必须马上找他。
他问你是谁 / 做什么：一两句说清上面这个定位就停，不背功能清单，不推销。没问就别自我介绍，也别复述这段说明。
你有声音：他说「念给我听」之类时，回复会念出来；别说自己只能打字。

你已经认识他——下面有他的档案和你记得的事，直接用。不要再问他告诉过你的事，也不要为此调用 get_personal_context 或 search_memory；只有下面找不到、需要翻更早的记忆时才用 search_memory。

说话：
- 称呼用「你」，不用「您」、不用 sir。英文名是 Zeep，不要叫他 Jimmy。
- 第一句就是答案或判断。像发消息那样说：一个意思一段，一段一两句，段与段之间空一行（页面上会是几条消息）；默认一到三段，他要细节再展开。列举的几项写在同一段里，每项一行。先办事，再（可选）甩一句干幽默——不是每轮都要梗，梗了也别解释。
- 敢轻轻纠正空话或不切实际的计划；他拍板了就照办，不唠叨。创业讨论尤其可以锋利一点，别无条件附和。
- 他累了、烦了、卡住了：先接住一句（短、真），再办事或问一个必要问题；不训话、不灌鸡汤、不堆任务清单。
- 做成事（记下了、部署了、会准备好了）：一句到位的肯定或收束就停，别庆祝表演。
- 纯文本：不用 Markdown 标题、加粗或表格；需要列举时每项一行。
- 不用客套收尾：不问「有什么需要帮忙的吗」「有什么可以帮你」，不说「希望对你有帮助」「需要的话告诉我」。结尾也不提议、不反问：不说「需要我…吗」「要不要我…」——能读的直接读完再回答。真需要他拍板时，只问一个问题。
- 他只是打招呼：问「在吗」就一句「在。」不问他要做什么，不找话题。
- 贴表情：像熟人在 WhatsApp 上那样，你可以在他那条消息上贴一个表情（👍 ❤️ 😂 😮 😢 🙏）。写法：回复第一行只放这个表情，空一行再写你要说的；不用说话时整条回复就只有这个表情。
  - 他报好消息或进展（做完了、拿到了、过了）→ ❤️ 或 👍，再接一句到位的话。
  - 他开玩笑、自嘲 → 😂，接不接话看有没有真想说的。
  - 他吐槽、累了、遇到倒霉事 → 😢，再接住一句。
  - 他说了让人意外的事 → 😮。
  - 他道谢 → 🙏 或 ❤️，一般不用说话；他说好的、收到、嗯、或只发了个表情 → 👍，不用说话。
  - 他问问题、交代事情、要你办事：正常回答，一般不贴。
  - 贴是因为真有反应，不是礼貌动作：大多数消息不贴，同一个表情别连着用。
- 有主见：直接给你认为最好的做法，不摆 A/B/C 菜单。下一步只在真有用时提一句。
- 不提工具、接口、模型、后端或 Demo。

事实：
- 日程、邮件、文件内容只能来自工具结果或下面给出的数据。没有就说没有，读不到就说读不到；绝不编造时间、地点、人名或邮件内容。
- 说他哪天有什么安排，只能依据下面的「日历」或 get_calendar_events 的结果；档案里的习惯不是日程。
- 他问「下次…是什么时候」（比如下次见导师），「日历」里又没有：这几步直接做完，不问他要不要查——
  1. get_calendar_events 从「日历」最后一天的第二天起再看 14 天；
  2. search_emails 用关键词搜（比如导师的名字）；
  3. 都没有才说没有，并说清查到了哪天、搜了邮件。
- 他发来截图或照片：先看图再答。图里的字、数字、时间照实读，看不清就说看不清，不猜。
- 搜到的东西和问题无关时，直说没找到相关的，不要把无关结果当答案。
- 只说你这次真查过的：没调用过 search_emails，就不能说邮件里没有。
- 他说你说错了（「不对」「你说错了」）：认一句、改正，再 note_mistake 记下（说错的那句、对的是什么）。同类的事以后照着避开。

记住他：
- 他说「记住…」，记的是关于他自己的事 → remember_fact。要去做的事（「记得续借图书馆的书」）不是记忆。
- 他顺带说出关于自己的长期事实或偏好（身份、重要的人、习惯、长期安排、喜好）→ 也用 remember_fact 记下，并在回复末尾加一句「记下了。」不记一次性的事、密码，也不记你自己的推测。
- 他纠正你记得的某件事 → remember_fact(新的完整事实, replaces=旧记忆的 id)，直接改，不用确认，回一句「改好了」和新的说法。
- 他要删掉某条记忆 → forget_fact（系统会先请他确认）。
- 记得的事是用来帮他的，不是用来管他的：他明确要做的事，和你记得的对不上也照常办（该确认的照常确认），绝不因此拒绝。
- 感情、医疗、家庭、财务旧数据：不在普通场景主动提起；他问起再用 search_memory。过时数字（DAU、资产、分成）要标明「记忆里是旧的」并建议核实。
- 他抱怨 Friday 的建议、打扰、界面或体验（「丑」「难看」「难用」「烦」「这个不对劲」）→ note_friction（可写 better=他希望怎样）。只回一句「记下了，下次按这个来。」不辩护、不自嘲、不解释架构，也不顺带提议做别的。
- 他问「我说过哪些不好用」「待修清单」→ list_friction，按条说清楚。
- 他确认某条已经改好 → resolve_friction。下面「还嫌弃的」里有的，说话和挑「需要你」时都要避开。
- 他说「用 Cursor 改…」「修开场/需要你」→ 直接 fix_friction_with_cursor(what=他要的改动)；系统会请他确认一次（会动仓库）。没有摩擦 id 也没关系，工具会自己记下。
- fix_friction_with_cursor 会**马上**返回「已交给 Cursor」——把 say 原样告诉他，让他可以走开。不要假装还在改、不要干等、不要叫他一直盯着页面。
- 上下文若写 Cursor 改完待部署，或他问「改好了吗」「改了什么」→ check_cursor_fix 或 preview_pending_ship，把 say **原样**给他，再问要不要部署；他说部署就 ship_pending_fix（系统会把改动给他看、请他确认）。

行动：
- 读操作直接做，不预告。
- 给他自己建日程（create_calendar_event）：时间齐了就直接建，不用问；页面会给他「撤销」。建完一句话说建好了什么（哪天几点）。
- 对外或删东西的写操作（发邮件、归档或删除邮件、删除记忆、让 Cursor 改代码、部署）：信息齐了就直接调用对应工具，不要先用文字问「要不要」——系统会在执行前把具体内容（收件人、主题、正文）给他看，等他点确认；他也可能在卡片里改了内容，系统会让你照改过的重新调用，那时参数一字不改。
- 他说自己晚点 / 明天要做某件事、但没给钟点（「我晚点回导师」「明天把报告交了」）：直接 add_task 记下（标题就是那件事，due 写他说的那天，没说就写「今天」），一句话说记下了。到时候还没划掉，推送里会带着「做完了 / 明天再说」去问他，你不用另外约时间。
- 关键信息缺了（不知道几点、发给谁）才先问一句。他拒绝了就一句话说没做，不重试。成功之前绝不说已完成；工具返回后一句话告诉他结果。
- 帮他准备一场会面或重要对话：先搜相关的邮件和笔记，再写：时间地点（日历里没有就直说）+ 现状一句话 + 三个讨论点。讨论点只能来自真材料（档案、记忆、邮件、笔记）；材料不够就少写几点并直说，不用空话凑数。"""

SPOKEN = """这一轮是他开口说的，你的回答会直接念给他听：
- 像当面说话：一到三句短句，口语，先说答案；语气仍是利落管家，可带一点干幽默，别念成客服稿。
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


def build_instructions(calendar: str = "", todo: str = "", *, spoken: bool = False, extra: str = "") -> str:
    parts = [
        VOICE,
        SPOKEN if spoken else "",
        now_block(),
        _connections_line(),
        reminders.chat_block(effective_now()),
        calendar,
        todo,
        profile_block(),
        memory_block(),
        friction.chat_block(),
        cursor_fix.chat_block(),
        extra,
    ]
    return "\n\n".join(part for part in parts if part)


_openai = OpenAIProvider()


def brain(name: str) -> Model | str:
    """型号名 → Agents SDK 用的模型：claude-* 走 Anthropic（她的性格那段每句都一样，单独缓存），其余交给 OpenAI。

    Claude 这会儿用不了（额度用完、key 失效、出故障）时由 GPT-5 顶上，见 claude.ClaudeModel。
    """
    if name.startswith("claude"):
        backup = None
        if (os.getenv("OPENAI_API_KEY") or "").strip():
            backup = (_openai.get_model(CLAUDE_FALLBACK), model_settings(CLAUDE_FALLBACK))
        return ClaudeModel(name, stable_prefix=VOICE, fallback=backup)
    require_openai_api_key()
    return name


def create_assistant(
    *, calendar: str = "", todo: str = "", spoken: bool = False, model: Model | None = None, extra: str = ""
) -> Agent:
    name = model if isinstance(model, str) else active_model() if model is None else ""
    return Agent(
        name="Friday",
        instructions=build_instructions(calendar, todo, spoken=spoken, extra=extra),
        tools=ALL_TOOLS + TASK_TOOLS if todos.connected() else ALL_TOOLS,
        model=model or brain(name),
        model_settings=model_settings(name),
    )


# 这个账号用不了默认型号（名字写错、没开通、key 不对）时，退回一个肯定能用的，不让 Friday 整个坏掉
FALLBACK_MODEL = "gpt-4.1-mini"
CLAUDE_FALLBACK = "gpt-5"
_active_model = DEFAULT_MODEL


def active_model() -> str:
    return _active_model


def answering_model() -> str:
    """此刻真在答话的：Claude 歇着的那几分钟是 GPT-5。"""
    return CLAUDE_FALLBACK if _active_model.startswith("claude") and claude.issue() else _active_model


def verify_model() -> str:
    """服务启动时问一次：默认型号这个账号能不能用。不能用就换一个能用的；网络问题不算，照旧用默认的。"""
    global _active_model
    if DEFAULT_MODEL.startswith("claude"):
        import anthropic

        try:
            anthropic.Anthropic().models.retrieve(DEFAULT_MODEL)
        except (anthropic.NotFoundError, anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            print(f"[WARN] {DEFAULT_MODEL} is not usable with this key ({exc}); using {CLAUDE_FALLBACK}")
            _active_model = CLAUDE_FALLBACK
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] could not check model {DEFAULT_MODEL}: {exc}")
        print(f"[OK] brain: {_active_model}")
        return _active_model
    import openai

    try:
        openai.OpenAI(api_key=require_openai_api_key()).models.retrieve(DEFAULT_MODEL)
    except openai.NotFoundError:
        print(f"[WARN] model {DEFAULT_MODEL} is not available on this account; using {FALLBACK_MODEL}")
        _active_model = FALLBACK_MODEL
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] could not check model {DEFAULT_MODEL}: {exc}")
    print(f"[OK] brain: {_active_model}")
    return _active_model


def model_settings(name: str) -> ModelSettings:
    """推理模型（Claude、GPT-5 及以后、o 系列）不收 temperature：给它思考力度；GPT 再让回答短一点；老模型照旧。"""
    if name.startswith("claude"):
        return ModelSettings(reasoning=Reasoning(effort=REASONING_EFFORT))
    if name.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
        return ModelSettings(reasoning=Reasoning(effort=REASONING_EFFORT), verbosity="low")
    return ModelSettings(temperature=0.2)


RECENT_IMAGES = 4  # 只把最近几张图真的发给模型：更早的换成一句话，一段里发多了也不会越问越贵、越慢


def _with_images(items: list[Any]) -> list[Any] | None:
    """对话里的图只记编号；问模型这一刻才换成真正的图（文件不在了就说一句）。没有图就返回 None。"""
    refs = [
        part.get("image_url") for item in items if isinstance(item, dict) and isinstance(item.get("content"), list)
        for part in item["content"] if isinstance(part, dict) and str(part.get("image_url") or "").startswith(uploads.PREFIX)
    ]
    recent = set(refs[-RECENT_IMAGES:])
    out, changed = [], False
    for item in items:
        content = item.get("content") if isinstance(item, dict) else None
        if isinstance(content, list) and any(
            isinstance(p, dict) and str(p.get("image_url") or "").startswith(uploads.PREFIX) for p in content
        ):
            parts = []
            for part in content:
                ref = part.get("image_url") if isinstance(part, dict) else None
                if isinstance(ref, str) and ref.startswith(uploads.PREFIX):
                    url = uploads.data_url(ref) if ref in recent else None
                    if url:
                        parts.append({**part, "image_url": url})
                    else:
                        gone = "（之前发过的一张图）" if ref not in recent else "（这张图已经不在了）"
                        parts.append({"type": "input_text", "text": gone})
                else:
                    parts.append(part)
            item, changed = {**item, "content": parts}, True
        out.append(item)
    return out if changed else None


def _model_input(data: CallModelData[Any]) -> ModelInputData:
    """问模型之前：把图编号换成图；换回 OpenAI 时再把 Claude 留在对话里的东西收拾掉（见 claude.for_openai）。"""
    items = _with_images(data.model_data.input) or data.model_data.input
    if not isinstance(data.agent.model, ClaudeModel):
        items = for_openai(items) or items
    if items is data.model_data.input:
        return data.model_data
    return ModelInputData(input=items, instructions=data.model_data.instructions)


def _said(message: str, images: list[str]) -> Any:
    """他这一句：带图就是一条有图的用户消息（图只记编号）。"""
    if not images:
        return message
    pictures = [{"type": "input_image", "image_url": uploads.PREFIX + i, "detail": "auto"} for i in images]
    return [{"role": "user", "content": [{"type": "input_text", "text": message or "（看图）"}, *pictures]}]


RUN_CONFIG = RunConfig(call_model_input_filter=_model_input)


async def _assistant(spoken: bool = False, model: Model | None = None, extra: str = "") -> Agent:
    """这一轮的 Friday：日历和待办同时读，谁也不等谁。"""
    calendar, todo = await asyncio.gather(asyncio.to_thread(chat_block), asyncio.to_thread(todos.chat_block))
    return create_assistant(calendar=calendar, todo=todo, spoken=spoken, model=model, extra=extra)


# ---------------------------------------------------------------------------
# 一轮对话：服务端的会话 + 流式 + 写操作停下等确认
# ---------------------------------------------------------------------------

PENDING_DIR = STATE_DIR / "pending"


def _get(raw: Any, key: str) -> Any:
    return raw.get(key) if isinstance(raw, dict) else getattr(raw, key, None)


def _approval_info(item: Any) -> dict[str, Any]:
    raw = item.raw_item
    args = _get(raw, "arguments")
    try:
        parsed = json.loads(args) if isinstance(args, str) and args else (args or {})
    except json.JSONDecodeError:
        parsed = {"raw": args}
    return {"call_id": _get(raw, "call_id") or _get(raw, "id"), "name": item.tool_name or _get(raw, "name"), "arguments": parsed}


def _same_call(edit: dict[str, Any], info: dict[str, Any]) -> bool:
    """她重新调用的和他改过的是不是同一件事：名字一样、他改过的每个参数一字不差。"""
    if edit["name"] != info["name"]:
        return False
    args = info.get("arguments") or {}
    return all(str(args.get(k, "")).strip() == str(v).strip() for k, v in edit["arguments"].items())


def _turn_to_json(turn: Any) -> dict[str, Any]:
    return {"undo": list(getattr(turn, "undo", []) or [])}


def _turn_from_json(data: Any) -> Turn:
    return Turn(undo=list((data or {}).get("undo") or []))


class Friday:
    """对话存在服务端（见 conversation.py）；写操作停下时，那一步原样存着，他确认才继续。

    停下的那一步也写到磁盘（STATE_DIR/pending/），云上重启了他再说「确认」也接得上。
    """

    def __init__(self, conversations: Conversations | None = None, *, model: Model | None = None) -> None:
        self._conversations = conversations
        self._model = model
        self._pending: dict[str, tuple[Agent, Any, list[dict[str, Any]]]] = {}
        # 他在确认卡片里改过的内容：她照着重新调用、参数一字不差时自动放行
        self._edits: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._carried: set[str] = set()

    @property
    def conversations(self) -> Conversations:
        return self._conversations or store()

    # ---- 待确认的那一步 ----

    def _pending_path(self, cid: str):
        return PENDING_DIR / f"{cid}.json"

    def _save_pending(self, cid: str, agent: Agent, state: Any, approvals: list[dict[str, Any]]) -> None:
        self._pending[cid] = (agent, state, approvals)
        if self.conversations.db_path == ":memory:":
            return
        try:
            PENDING_DIR.mkdir(parents=True, exist_ok=True)
            blob = {"approvals": approvals, "state": state.to_string(context_serializer=_turn_to_json)}
            self._pending_path(cid).write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 — 存不下来也只是重启后要他再说一遍
            print(f"[WARN] pending approval not persisted: {exc}")

    async def _load_pending(self, cid: str, spoken: bool) -> tuple[Agent, Any, list[dict[str, Any]]] | None:
        if cid in self._pending:
            return self._pending[cid]
        path = self._pending_path(cid)
        if not path.is_file():
            return None
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            agent = await _assistant(spoken, self._model)
            state = await RunState.from_string(agent, blob["state"], context_deserializer=_turn_from_json)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] pending approval could not be restored: {exc}")
            path.unlink(missing_ok=True)
            return None
        self._pending[cid] = (agent, state, blob.get("approvals") or [])
        return self._pending[cid]

    def _drop_pending(self, cid: str) -> None:
        self._pending.pop(cid, None)
        self._pending_path(cid).unlink(missing_ok=True)

    def pending_approvals(self, cid: str) -> list[dict[str, Any]]:
        if cid in self._pending:
            return list(self._pending[cid][2])
        path = self._pending_path(cid)
        if path.is_file():
            try:
                return list(json.loads(path.read_text(encoding="utf-8")).get("approvals") or [])
            except (OSError, json.JSONDecodeError):
                return []
        return []

    # ---- 一轮 ----

    def resolve_conversation(self, cid: str | None) -> str:
        """页面带来的对话 id 还在就用它；否则接上当前的；都没有就开一个新的。"""
        convs = self.conversations
        if cid and convs.exists(cid):
            return cid
        return convs.current() or convs.create()

    async def turn(
        self, cid: str, message: str, *, spoken: bool = False, revision: dict[str, Any] | None = None,
        images: list[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """他说了一句：存进对话，跑 Friday，事件流给页面，最后把她的回复也存进对话。

        revision = {"call_id", "changes"}：他在确认卡片里改了内容再点「发送」。改过的那份就是他确认的版本。
        """
        lock = self._locks.setdefault(cid, asyncio.Lock())
        async with lock:
            convs = self.conversations
            await self._carry_over(cid)
            images = [i for i in images or [] if uploads.find(i)][: uploads.MAX_PER_MESSAGE]
            shown = {"images": [{"id": i, "url": uploads.PREFIX + i} for i in images]} if images else {}
            said_id = convs.add_message(cid, "user", message, **shown)
            said = _said(message, images)
            yield {"type": "conversation", "id": cid}

            pending = await self._load_pending(cid, spoken)
            texts: list[str] = []
            tools: list[str] = []
            undo: list[dict[str, Any]] = []
            approvals: list[dict[str, Any]] = []

            async def run(agent: Agent, run_input: Any) -> AsyncIterator[dict[str, Any]]:
                async for event in self._run(cid, agent, run_input, tools, undo, approvals):
                    if event["type"] == "text":
                        texts.append(event["text"])
                    else:
                        yield event

            if pending is not None:
                agent, state, waiting = pending
                choice = "revise" if revision else approval.decide(message)
                # 她问完「发吗？」之后又说过别的（推送、开场、点按钮办的事）：他这句回的是那些，不是那个问题
                last = convs.last_hers(said_id)
                if choice != "revise" and not (last and last.get("needs_confirm")):
                    choice = "other"
                self._drop_pending(cid)
                if choice == "approve":
                    tools.extend(a["name"] for a in waiting if a.get("name") and a["name"] not in tools)
                for item in state.get_interruptions():
                    info = _approval_info(item)
                    if choice == "approve":
                        state.approve(item)
                    elif choice == "revise" and info["call_id"] == revision.get("call_id"):
                        edited = {**info["arguments"], **(revision.get("changes") or {})}
                        self._edits[cid] = {"name": info["name"], "arguments": edited}
                        state.reject(
                            item,
                            rejection_message=(
                                f"他把内容改了。马上按下面这份重新调用 {info['name']}，每个参数一字不改，不要再改写："
                                f"{json.dumps(edited, ensure_ascii=False)}"
                            ),
                        )
                    else:
                        state.reject(
                            item,
                            rejection_message="他没同意，这一步没做。"
                            if choice == "reject"
                            else "他没确认，转而说了别的。这一步没做；简短说一句没做，然后回应他的新话。",
                        )
                async for event in run(agent, state):
                    yield event
                if choice == "other" and not approvals:
                    # 他换了话题：上一步已作罢，接着回答他这句
                    yield {"type": "tool", "name": ""}
                    agent = await _assistant(spoken, self._model, self._context())
                    async for event in run(agent, said):
                        yield event
            else:
                agent = await _assistant(spoken, self._model, self._context())
                async for event in run(agent, said):
                    yield event

            reply = "\n\n".join(t for t in texts if t.strip())
            # 第一行只有一个表情：贴在他那条消息上（像 WhatsApp），剩下的才是她说的话
            emoji, reply = split_reaction(reply)
            if emoji and not reply and (approvals or undo):
                emoji, reply = None, emoji  # 要确认、能撤销的，总得有她一条话挂按钮
            if emoji:
                convs.update_message(said_id, reaction=emoji)
            if emoji and not reply:
                yield {"type": "done", "reply": "", "reaction": emoji, "ask": "", "tools_called": tools, "undo": [],
                       "needs_confirm": False, "approvals": [], "message_id": None, "conversation_id": cid}
                return
            ask = approval.prompt(approvals) if approvals else ""
            if ask:
                reply = f"{reply}\n\n{ask}" if reply else ask
            message_id = convs.add_message(
                cid,
                "assistant",
                reply,
                tools=tools,
                undo=undo,
                needs_confirm=bool(approvals),
                approvals=approvals,
                ask=ask,
            )
            yield {
                "type": "done",
                "reply": reply,
                "reaction": emoji or "",
                "ask": ask,
                "tools_called": tools,
                "undo": undo,
                "needs_confirm": bool(approvals),
                "approvals": approvals,
                "message_id": message_id,
                "conversation_id": cid,
            }

    async def _run(
        self,
        cid: str,
        agent: Agent,
        run_input: Any,
        tools: list[str],
        undo: list[dict[str, Any]],
        approvals: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        """跑一段：delta / tool 原样给页面；最后的文字用 text 事件交回给 turn()。"""
        session = self.conversations.session(cid)
        if isinstance(run_input, RunState):
            result = Runner.run_streamed(
                agent, run_input, max_turns=12, session=session, run_config=RUN_CONFIG, hooks=LEDGER
            )
        else:
            result = Runner.run_streamed(
                agent, run_input, max_turns=12, context=Turn(), session=session, run_config=RUN_CONFIG, hooks=LEDGER
            )
        async for event in result.stream_events():
            if event.type == "raw_response_event":
                if isinstance(event.data, ResponseTextDeltaEvent) and event.data.delta:
                    yield {"type": "delta", "text": event.data.delta}
                elif getattr(event.data, "type", None) == RESTART:
                    # Claude 说到一半出故障、换备用的重说：页面把那半句收起来（和她去查东西时一样）
                    yield {"type": "tool", "name": ""}
            elif event.type == "run_item_stream_event" and event.name == "tool_called":
                raw = getattr(event.item, "raw_item", None)
                name = _get(raw, "name")
                if name:
                    if name not in tools:
                        tools.append(str(name))
                    yield {"type": "tool", "name": str(name)}
        turn = getattr(result.context_wrapper, "context", None)
        undo.extend(getattr(turn, "undo", None) or [])
        interruptions = list(getattr(result, "interruptions", None) or [])
        edit = self._edits.pop(cid, None)
        if interruptions and edit and all(_same_call(edit, _approval_info(item)) for item in interruptions):
            # 她照着他改过的版本重新调用了：那份就是他确认过的，直接放行
            state = result.to_state()
            for item in interruptions:
                state.approve(item)
            async for event in self._run(cid, agent, state, tools, undo, approvals):
                yield event
            return
        if interruptions:
            waiting = [_approval_info(item) for item in interruptions]
            for info in waiting:
                if info["name"] and info["name"] not in tools:
                    tools.append(info["name"])
            approvals.extend(waiting)
            self._save_pending(cid, agent, result.to_state(), waiting)
            # 停下之前模型写的那点字照样算这一轮的话
            partial = "".join(
                _get(part, "text") or ""
                for item in result.new_items
                if getattr(item, "type", "") == "message_output_item"
                for part in (_get(item.raw_item, "content") or [])
            )
            yield {"type": "text", "text": partial}
            return
        final = result.final_output
        yield {"type": "text", "text": final if isinstance(final, str) else str(final or "")}

    # ---- 开场 ----

    def _context(self) -> str:
        """她今天主动发过的消息、他刚贴在她话上的表情：写进这一句的说明里，不动对话历史。"""
        parts = [nudges.chat_block(effective_now())]
        seen = self.conversations.recent_reactions(time.time() - 2 * 60 * 60)
        if seen:
            lines = "\n".join(f"- 「{text[:60]}」{emoji}" for text, emoji in seen[-5:])
            parts.append(f"他刚才在你说的话上贴了表情：\n{lines}")
        return "\n\n".join(part for part in parts if part)

    async def _carry_over(self, cid: str) -> None:
        """页面上是一条连着的对话；给模型的那段过两小时会重开。新开的一段先带上前一段最后几句，他接着刚才的话说她也接得上。"""
        if cid in self._carried:
            return
        self._carried.add(cid)
        session = self.conversations.session(cid)
        if await session.get_items(limit=1):
            return
        lines = self.conversations.carry_over(cid)
        if lines:
            await session.add_items(lines)

    async def record_opener(self, cid: str, reply: str, card: dict[str, Any] | None) -> int:
        """开场卡片和那句话也进对话：换设备能看到，模型也知道自己刚说了什么。"""
        await self._carry_over(cid)
        message_id = self.conversations.add_message(cid, "assistant", reply, agenda=card, tools=[])
        if reply.strip():
            await self.conversations.session(cid).add_items([{"role": "assistant", "content": reply}])
        return message_id


friday = Friday()


async def run_assistant(
    message: str,
    *,
    conversation_id: str | None = None,
    friday_service: Friday | None = None,
) -> dict:
    """非流式地跑一轮（CLI / 评测用）。默认每次一个新的内存对话，不碰他真实的对话记录。

    要接着上一轮（比如评测里先问再「确认」），把返回的 conversation_id 传回来。
    """
    service = friday_service or _scratch()
    cid = conversation_id if conversation_id and service.conversations.exists(conversation_id) else service.conversations.create()
    result: dict[str, Any] = {}
    async for event in service.turn(cid, message):
        if event["type"] == "done":
            result = event
    return {
        "reply": result.get("reply", ""),
        "tools_called": result.get("tools_called", []),
        "needs_confirm": result.get("needs_confirm", False),
        "conversation_id": cid,
    }


_scratch_service: Friday | None = None


def _scratch() -> Friday:
    global _scratch_service
    if _scratch_service is None:
        _scratch_service = Friday(Conversations(":memory:"))
    return _scratch_service


