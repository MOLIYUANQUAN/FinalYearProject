"""Friday 的本地入口：一个页面 + 流式对话。"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import agenda, mistakes, todos, usage_log, voice
from src.agent import friday, run_assistant
from src.presence import stream_presence
from src.access import gate, router as access_router
from src.state_sync import router as state_router
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
    yield


app = FastAPI(
    title="Friday",
    version="0.5.0",
    lifespan=lifespan,
)
app.middleware("http")(gate)
app.include_router(access_router)
app.include_router(state_router)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户自然语言输入")
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
        "has_openai_api_key": has_key,
        "calendar_backend": backend,
        "mail_backend": mail,
        "tasks_backend": tasks,
        "access_required": bool(get_access_token()),
        "effective_today": effective_today(),
        "effective_tomorrow": effective_tomorrow(),
        "now_label": f"{now.month}月{now.day}日 {weekday_zh(now)}",
    }


def _require_key() -> None:
    try:
        require_openai_api_key()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _parse_chat(body: ChatRequest) -> str:
    message = body.message.strip()
    if not message:
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
            error = {"type": "error", "message": f"出了点问题：{exc}"}
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


@app.get("/api/conversation")
def conversation_current() -> dict:
    """页面打开时：接上当前这段对话（手机上聊的，电脑上也看得到）；过期了就是空的。"""
    cid = friday.conversations.current()
    if not cid:
        return {"id": None, "messages": []}
    messages = friday.conversations.messages(cid)
    # 待确认的那一步如果已经没了（比如很久以前的），按钮就别再显示
    if messages and messages[-1].get("needs_confirm") and not friday.pending_approvals(cid):
        messages[-1]["needs_confirm"] = False
    return {"id": cid, "messages": messages}


@app.post("/api/conversation/new")
def conversation_new() -> dict:
    return {"id": friday.conversations.create()}


async def _presence_events(cid: str) -> AsyncIterator[dict[str, Any]]:
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
    kind: str = Field(..., pattern="^(task_added|task_completed|task_due_changed)$")
    id: str = Field(..., min_length=1)
    due: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class UndoRequest(BaseModel):
    items: list[UndoItem] = Field(..., min_length=1)
    message_id: int | None = Field(None, description="对话里那条消息：撤销后标上「已撤销」，换设备也看得到")


@app.post("/api/undo")
def undo(body: UndoRequest) -> dict:
    """他点了「撤销」：直接撤回刚才那一步，不经过模型。"""
    try:
        todos.undo([item.model_dump() for item in body.items])
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).splitlines()[0] if isinstance(exc, RuntimeError) else "待办这次没连上"
        raise HTTPException(status_code=502, detail=f"没撤销成功：{reason}") from exc
    if body.message_id is not None:
        friday.conversations.update_message(body.message_id, undone=True)
    return {"ok": True}


class WrongRequest(BaseModel):
    message_id: int
    note: str = Field("", max_length=500)


@app.post("/api/wrong")
def wrong(body: WrongRequest) -> dict:
    """他点了「说错了」：把那句话、他问的是什么、用了哪些工具记下来，之后补成测试。不经过模型。"""
    convs = friday.conversations
    cid = convs.conversation_of(body.message_id)
    if cid is None:
        raise HTTPException(status_code=404, detail="找不到这条消息。")
    messages = convs.messages(cid)
    index = next(i for i, m in enumerate(messages) if m["id"] == body.message_id)
    said = messages[index]
    asked = next((m["content"] for m in reversed(messages[:index]) if m["role"] == "user"), "")
    mistakes.record(
        asked=asked,
        said=said["content"],
        tools=said.get("tools") or [],
        opener=bool(said.get("agenda")),
        note=body.note,
    )
    convs.update_message(body.message_id, wrong=True)
    usage_log.record("wrong", ok=True, first_token_ms=None, total_ms=0, tools=said.get("tools") or [])
    return {"ok": True}


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    _require_key()
    message = _parse_chat(body)
    cid = friday.resolve_conversation(body.conversation_id)
    return _sse("chat", friday.turn(cid, message, spoken=body.spoken))


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


@app.post("/api/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...)) -> dict:
    """网页录的一段音 → 文字；再走原来的对话。"""
    _require_key()
    data = await file.read()
    try:
        text = await asyncio.to_thread(voice.transcribe, data, file.filename or "audio.webm")
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).splitlines()[0]
        raise HTTPException(status_code=502, detail=f"没听清：{reason}") from exc
    if not text:
        raise HTTPException(status_code=400, detail="没听清，再说一遍？")
    return {"text": text}


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
