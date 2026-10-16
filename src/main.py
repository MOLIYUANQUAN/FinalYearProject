"""FastAPI 本地入口：一个页面 + 流式对话。"""

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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import usage_log
from src.agent import run_assistant, stream_assistant, stream_presence
from src.config import (
    STATIC_DIR,
    effective_now,
    effective_today,
    effective_tomorrow,
    get_calendar_backend,
    get_mail_backend,
    require_openai_api_key,
)
from src.context import weekday_zh


def _warm_calendar() -> None:
    try:
        from src.calendar_providers.google_cal import warm_up

        warm_up()
        print("[OK] Google Calendar ready")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Google Calendar warm-up skipped: {exc}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
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
    _warm = asyncio.create_task(asyncio.to_thread(_warm_calendar)) if backend == "google" else None
    yield


app = FastAPI(
    title="Personal Agent",
    version="0.4.0",
    lifespan=lifespan,
)


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
    return {
        "ok": True,
        "has_openai_api_key": has_key,
        "calendar_backend": backend,
        "mail_backend": mail,
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
                if event["type"] == "delta" and first_token_ms is None:
                    first_token_ms = int((time.perf_counter() - started) * 1000)
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
    """打开时的第一句话：此刻 + 今明两天的真实日历。"""
    _require_key()
    return _sse("presence", stream_presence())


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
    import uvicorn

    uvicorn.run("src.main:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
