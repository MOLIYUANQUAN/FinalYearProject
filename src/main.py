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

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import agenda, todos, usage_log
from src.agent import run_assistant, stream_assistant
from src.presence import stream_presence
from src.access import gate
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


class ChatTurn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户自然语言输入")
    history: list[ChatTurn] = Field(
        default_factory=list,
        description="本次会话此前的对话（不含本轮 message）",
    )
    pending_confirmation: bool = Field(
        False,
        description="上一轮是否在等他确认写操作；只有这时「确认/好的」才算同意",
    )


class ChatResponse(BaseModel):
    reply: str
    tools_called: list[str]
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


def _parse_chat(body: ChatRequest) -> tuple[str, list[dict[str, str]]]:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    history = [{"role": t.role, "content": t.content.strip()} for t in body.history]
    # 限制历史长度，避免上下文过长
    return message, history[-20:]


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


@app.post("/api/presence/stream")
async def presence_stream() -> StreamingResponse:
    """打开时的「今天」：真实日历排成的卡片，加一句此刻最该知道的话。"""
    _require_key()
    return _sse("presence", stream_presence())


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


@app.post("/api/undo")
def undo(body: UndoRequest) -> dict:
    """他点了「撤销」：直接撤回刚才那一步，不经过模型。"""
    try:
        todos.undo([item.model_dump() for item in body.items])
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).splitlines()[0] if isinstance(exc, RuntimeError) else "待办这次没连上"
        raise HTTPException(status_code=502, detail=f"没撤销成功：{reason}") from exc
    return {"ok": True}


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    _require_key()
    message, history = _parse_chat(body)
    return _sse(
        "chat",
        stream_assistant(
            message,
            history=history,
            pending_confirmation=body.pending_confirmation,
        ),
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    """非流式版本，供 CLI / 评测脚本使用。"""
    _require_key()
    message, history = _parse_chat(body)
    try:
        result = await run_assistant(
            message,
            history=history,
            pending_confirmation=body.pending_confirmation,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"助手运行失败: {exc}") from exc

    return ChatResponse(
        reply=result["reply"],
        tools_called=result["tools_called"],
        calendar_backend=get_calendar_backend(),
        effective_today=effective_today(),
        effective_tomorrow=effective_tomorrow(),
    )


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
