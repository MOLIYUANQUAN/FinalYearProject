"""Friday 的本地入口：一个页面 + 流式对话。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import agenda, claude, closed, live, reminders, todos, usage_log, voice
from src.agent import answering_model, friday, run_assistant, verify_model
from src.conversation import REACTIONS
from src.calendar_providers import get_calendar_provider
from src.presence import stream_presence
from src.access import authorized, gate, router as access_router
from src.push_api import router as push_router, run_scheduler, scheduler_enabled
from src.state_sync import router as state_router
from src.about import router as about_router
from src.uploads import MAX_PER_MESSAGE, router as uploads_router
from src.workbench import router as workbench_router
from src.config import (
    STATIC_DIR,
    effective_now,
    effective_today,
    effective_tomorrow,
    get_access_token,
    get_calendar_backend,
    get_mail_backend,
    get_tasks_backend,
    materialize_secrets_from_env,
    require_openai_api_key,
)
from src.context import weekday_zh
from src.version import code_version

CODE_VERSION = code_version()


def _warm_calendar() -> None:
    try:
        from src.calendar_providers.google_cal import warm_up

        warm_up()
        print("[OK] Google Calendar ready")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Google Calendar warm-up skipped: {exc}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    written = materialize_secrets_from_env()
    if written:
        print(f"[OK] secrets from env: {', '.join(written)}")
    try:
        require_openai_api_key()
        print("[OK] OPENAI_API_KEY loaded")
    except RuntimeError as exc:
        print(f"[WARN] {exc}")
        print("  Server started, but chat returns 503 until a valid key is set.")
    backend = None
    try:
        backend = get_calendar_backend()
        print(f"[OK] CALENDAR_BACKEND={backend}")
    except RuntimeError as exc:
        print(f"[WARN] {exc}")
    try:
        print(f"[OK] MAIL_BACKEND={get_mail_backend()}")
    except RuntimeError as exc:
        print(f"[WARN] {exc}")
    try:
        print(f"[OK] TASKS_BACKEND={get_tasks_backend()}")
    except RuntimeError as exc:
        print(f"[WARN] {exc}")
    if get_access_token():
        print("[OK] FRIDAY_ACCESS_TOKEN set (remote access gated)")
    else:
        print("[WARN] FRIDAY_ACCESS_TOKEN unset — set it before exposing Friday on the public internet")
    _warm = asyncio.create_task(asyncio.to_thread(_warm_calendar)) if backend == "google" else None
    nudger = asyncio.create_task(run_scheduler()) if scheduler_enabled() else None
    asyncio.create_task(asyncio.to_thread(verify_model))
    print(f"[OK] nudges {'on' if nudger else 'off'}")
    yield
    if nudger:
        nudger.cancel()


app = FastAPI(
    title="Friday",
    version="0.5.0",
    lifespan=lifespan,
)
app.middleware("http")(gate)
app.include_router(access_router)
app.include_router(state_router)
app.include_router(push_router)
app.include_router(workbench_router)
app.include_router(uploads_router)
app.include_router(about_router)


class ChatRequest(BaseModel):
    message: str = Field("", description="用户自然语言输入；只发图时可以是空的")
    images: list[str] = Field(default_factory=list, max_length=MAX_PER_MESSAGE, description="先传到 /api/uploads 的图的编号")
    conversation_id: str | None = Field(
        None,
        max_length=64,
        description="页面上这段对话的 id；没有或过期了就接上当前对话 / 开新的。历史在服务端，不用传。",
    )
    spoken: bool = Field(False, description="他是开口说的：回答会被念出来")


class PresenceRequest(BaseModel):
    conversation_id: str | None = Field(None, max_length=64)


class ChatResponse(BaseModel):
    reply: str
    tools_called: list[str]
    needs_confirm: bool = False
    conversation_id: str = ""
    calendar_backend: str = "mock"
    effective_today: str = ""
    effective_tomorrow: str = ""


@app.get("/")
def index() -> FileResponse:
    # 避免浏览器缓存旧 JS（否则会话恢复 / 确认闭环会失效）
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@app.get("/privacy")
def privacy() -> FileResponse:
    """Google OAuth 正式版要求的隐私政策（公开页面，不含任何数据）。"""
    return FileResponse(STATIC_DIR / "privacy.html")


@app.get("/api/health")
def health() -> dict:
    has_key = True
    try:
        require_openai_api_key()
    except RuntimeError:
        has_key = False
    backend = "mock"
    try:
        backend = get_calendar_backend()
    except RuntimeError:
        pass
    mail = "none"
    try:
        mail = get_mail_backend()
    except RuntimeError:
        pass
    now = effective_now()
    tasks = "none"
    try:
        tasks = get_tasks_backend()
    except RuntimeError:
        pass
    return {
        "ok": True,
        "code_version": CODE_VERSION,
        # 云上部署时带进来的提交号：部署工作流靠它确认线上就是刚推的那一版
        "git_sha": (os.getenv("FRIDAY_GIT_SHA") or "").strip(),
        "model": answering_model(),
        "claude_issue": claude.issue(),
        "has_openai_api_key": has_key,
        "calendar_backend": backend,
        "mail_backend": mail,
        "mailboxes": _mailbox_names(),
        "tasks_backend": tasks,
        "access_required": bool(get_access_token()),
        "effective_today": effective_today(),
        "effective_tomorrow": effective_tomorrow(),
        "now_label": f"{now.month}月{now.day}日 {weekday_zh(now)}",
    }


def _mailbox_names() -> list[str]:
    try:
        from src.mail_providers import label_of, mailboxes

        return [label_of(box) for box in mailboxes()]
    except RuntimeError:
        return []


def _require_key() -> None:
    try:
        require_openai_api_key()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _parse_chat(body: ChatRequest) -> str:
    message = body.message.strip()
    if not message and not body.images:
        raise HTTPException(status_code=400, detail="消息不能为空")
    return message


def _sse(kind: str, events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    async def body() -> AsyncIterator[str]:
        started = time.perf_counter()
        first_token_ms: int | None = None
        tools: list[str] = []
        ok = True
        try:
            async for event in events:
                # 开场的安排卡片和文字一样，是他最先看到的内容
                if event["type"] in ("delta", "agenda") and first_token_ms is None:
                    first_token_ms = int((time.perf_counter() - started) * 1000)
                if event["type"] == "agenda" and event.get("error"):
                    ok = False
                elif event["type"] == "done":
                    tools = list(event.get("tools_called") or [])
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            ok = False
            # 他只看到她说一句；具体哪里坏了写进日志（flyctl logs）
            print(f"[ERROR] {kind}: {exc!r}")
            error = {"type": "error", "message": "这句没接上，再说一次。", "detail": str(exc)}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
        finally:
            usage_log.record(
                kind,
                ok=ok,
                first_token_ms=first_token_ms,
                total_ms=int((time.perf_counter() - started) * 1000),
                tools=tools,
            )

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ReactBody(BaseModel):
    message_id: int
    part: int = Field(0, ge=0, le=50, description="她那条消息的第几段（一段一个气泡）")
    emoji: str = Field("", max_length=8, description="空的就是拿掉")


@app.post("/api/react")
def react(body: ReactBody) -> dict:
    """他在她的某个气泡上贴表情（再点同一个就拿掉）。不经过模型；他下次说话时她看得到。"""
    if body.emoji and body.emoji not in REACTIONS:
        raise HTTPException(status_code=400, detail="只能贴这几个表情。")
    message = friday.conversations.message(body.message_id)
    if message is None or message["role"] == "user":
        raise HTTPException(status_code=404, detail="这条消息不在了。")
    reactions = dict(message.get("reactions") or {})
    if body.emoji:
        reactions[str(body.part)] = body.emoji
    else:
        reactions.pop(str(body.part), None)
    friday.conversations.update_message(body.message_id, reactions=reactions, reacted_at=time.time())
    return {"ok": True, "reactions": reactions}


@app.get("/api/conversation")
def conversation_current() -> dict:
    """页面打开时：那一条对话（手机上聊的，电脑上也看得到）。id 是给模型的那一段；放久了是 None，页面就请她开场。"""
    messages = friday.conversations.thread()
    current = friday.conversations.current()
    # 待确认的按钮只在那一段还没结束、那一步还等着时显示（隔夜的、已经没了的就别再给他点）
    last = messages[-1] if messages else None
    if last and last.get("needs_confirm") and (
        last["conversation_id"] != current or not friday.pending_approvals(last["conversation_id"])
    ):
        last["needs_confirm"] = False
    return {"id": current, "messages": messages}


async def _presence_events(cid: str) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "conversation", "id": cid}
    card: dict[str, Any] | None = None
    async for event in stream_presence():
        if event["type"] == "agenda":
            card = {k: v for k, v in event.items() if k != "type"}
        if event["type"] == "done":
            event = {**event, "message_id": await friday.record_opener(cid, event.get("reply") or "", card)}
        yield event


@app.post("/api/presence/stream")
async def presence_stream(body: PresenceRequest | None = None) -> StreamingResponse:
    """打开时的「今天」：真实日历排成的卡片，加一句此刻最该知道的话。也记进这段对话。"""
    _require_key()
    cid = friday.resolve_conversation(body.conversation_id if body else None)
    return _sse("presence", _presence_events(cid))


@app.post("/api/calendar/warm", status_code=204)
def calendar_warm() -> Response:
    """窗口被叫回时先把日历读好：他打完字，这一轮就不用再等日历。"""
    agenda.refresh_soon()
    return Response(status_code=204)


class UndoItem(BaseModel):
    kind: str = Field(
        ..., pattern="^(task_added|task_completed|task_due_changed|event_created|reminder_added|reminder_cancelled)$"
    )
    id: str = Field(..., min_length=1)
    due: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class UndoRequest(BaseModel):
    items: list[UndoItem] = Field(..., min_length=1)
    message_id: int | None = Field(None, description="对话里那条消息：撤销后标上「已撤销」，换设备也看得到")


@app.post("/api/undo")
def undo(body: UndoRequest) -> dict:
    """他点了「撤销」：直接撤回刚才那一步，不经过模型。"""
    items = [item.model_dump() for item in body.items]
    tasks = [item for item in items if item["kind"].startswith("task_")]
    for item in items:
        if item["kind"] == "task_completed":
            closed.remove(f"task:{item['id']}")
    events = [item for item in items if item["kind"] == "event_created"]
    try:
        if tasks:
            todos.undo(tasks)
        for item in reversed(events):
            get_calendar_provider().delete_event(item["id"])
            agenda.forget()
        for item in reversed(items):
            if item["kind"] == "reminder_added":
                reminders.cancel(item["id"])
            elif item["kind"] == "reminder_cancelled":
                reminders.restore(item["id"])
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).splitlines()[0] if isinstance(exc, RuntimeError) else "这次没连上"
        raise HTTPException(status_code=502, detail=f"没撤销成功：{reason}") from exc
    if body.message_id is not None:
        friday.conversations.update_message(body.message_id, undone=True)
    return {"ok": True}


class ReviseRequest(BaseModel):
    conversation_id: str = Field(..., max_length=64)
    call_id: str = Field(..., max_length=200)
    changes: dict[str, str] = Field(..., description="他在确认卡片里改过的字段，比如 subject / body")


# 卡片里能改的：邮件的主题和正文（收件人不让在这里改，要改就跟她说）
REVISABLE = {"subject", "body"}


@app.post("/api/chat/revise")
async def chat_revise(body: ReviseRequest) -> StreamingResponse:
    """他在确认卡片里改了再点「发送」：改过的那份就是他确认的版本。"""
    _require_key()
    changes = {k: v for k, v in body.changes.items() if k in REVISABLE}
    if not changes:
        raise HTTPException(status_code=400, detail="没有能改的内容。")
    if not any(a.get("call_id") == body.call_id for a in friday.pending_approvals(body.conversation_id)):
        raise HTTPException(status_code=409, detail="这一步已经不在等确认了。")
    return _sse(
        "chat",
        friday.turn(body.conversation_id, "（改了一下）按这个发。", revision={"call_id": body.call_id, "changes": changes}),
    )


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    _require_key()
    message = _parse_chat(body)
    cid = friday.resolve_conversation(body.conversation_id)
    return _sse("chat", friday.turn(cid, message, spoken=body.spoken, images=body.images))


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    """非流式版本，供 CLI / 评测脚本使用。"""
    _require_key()
    message = _parse_chat(body)
    try:
        result = await run_assistant(message, conversation_id=body.conversation_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"助手运行失败: {exc}") from exc

    return ChatResponse(
        reply=result["reply"],
        tools_called=result["tools_called"],
        needs_confirm=result["needs_confirm"],
        conversation_id=result["conversation_id"],
        calendar_backend=get_calendar_backend(),
        effective_today=effective_today(),
        effective_tomorrow=effective_tomorrow(),
    )


class SpeakBody(BaseModel):
    text: str = Field(..., min_length=1)


@app.websocket("/api/voice/live")
async def voice_live(page: WebSocket) -> None:
    """按住时边说边出字（见 live.py）。网页的登录检查管不到 WebSocket，这里自己查。"""
    origin = urlparse(page.headers.get("origin") or "").netloc
    if not authorized(page) or (origin and origin != page.headers.get("host")):  # type: ignore[arg-type]
        await page.close(code=1008)
        return
    await live.relay(page)


@app.post("/api/voice/ask")
async def voice_ask(file: UploadFile = File(...), conversation_id: str | None = Form(None)) -> StreamingResponse:
    """按住说话松手：整段录音转写完就接着回答。先回 {"type": "heard"} 让气泡填上他说的话（换掉边说边出的预览）。"""
    _require_key()
    data = await file.read()
    try:
        text = await asyncio.to_thread(voice.transcribe, data, file.filename or "audio.webm")
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).splitlines()[0]
        raise HTTPException(status_code=502, detail=f"没听清：{reason}") from exc
    if not text:
        raise HTTPException(status_code=400, detail="没听清，再说一遍？")
    cid = friday.resolve_conversation(conversation_id)
    spoken = voice.wants_voice(text)

    async def events() -> AsyncIterator[dict[str, Any]]:
        yield {"type": "heard", "text": text, "spoken": spoken}
        async for event in friday.turn(cid, text, spoken=spoken):
            yield event

    return _sse("chat", events())


@app.post("/api/voice/speak")
async def voice_speak(body: SpeakBody) -> Response:
    """把回复念出来（mp3）。"""
    _require_key()
    try:
        audio = await asyncio.to_thread(voice.speak, body.text)
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).splitlines()[0]
        raise HTTPException(status_code=502, detail=f"这句没念出来：{reason}") from exc
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    import os

    import uvicorn

    # 本机默认只听 127.0.0.1；云上设 PORT（或 HOST=0.0.0.0）对外
    port = int(os.getenv("PORT") or "8765")
    host = (os.getenv("HOST") or ("0.0.0.0" if os.getenv("PORT") else "127.0.0.1")).strip()
    uvicorn.run("src.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
