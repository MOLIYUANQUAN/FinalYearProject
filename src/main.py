"""FastAPI 极简 Web UI 入口。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.agent import run_assistant
from src.config import (
    STATIC_DIR,
    effective_today,
    effective_tomorrow,
    get_calendar_backend,
    get_mail_backend,
    require_openai_api_key,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        require_openai_api_key()
        print("[OK] OPENAI_API_KEY loaded")
    except RuntimeError as exc:
        print(f"[WARN] {exc}")
        print("  Server started, but /api/chat returns 503 until a valid key is set.")
    try:
        backend = get_calendar_backend()
        print(f"[OK] CALENDAR_BACKEND={backend}")
    except RuntimeError as exc:
        print(f"[WARN] {exc}")
    try:
        print(f"[OK] MAIL_BACKEND={get_mail_backend()}")
    except RuntimeError as exc:
        print(f"[WARN] {exc}")
    yield


app = FastAPI(
    title="Personal AI Assistant",
    version="0.2.0",
    lifespan=lifespan,
)


class ChatTurn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户自然语言输入")
    history: list[ChatTurn] = Field(
        default_factory=list,
        description="此前多轮对话（不含本轮 message），用于确认闭环",
    )


class ChatResponse(BaseModel):
    reply: str
    tools_called: list[str]
    calendar_backend: str = "mock"
    effective_today: str = ""
    effective_tomorrow: str = ""


@app.get("/")
def index() -> FileResponse:
    # 避免浏览器缓存旧 JS（否则多轮 history / 确认闭环会失效）
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
    return {
        "ok": True,
        "has_openai_api_key": has_key,
        "calendar_backend": backend,
        "mail_backend": mail,
        "effective_today": effective_today(),
        "effective_tomorrow": effective_tomorrow(),
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    try:
        require_openai_api_key()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    history = [{"role": t.role, "content": t.content.strip()} for t in body.history]
    # 限制历史长度，避免上下文过长
    if len(history) > 20:
        history = history[-20:]

    try:
        result = await run_assistant(message, history=history)
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
