"""FastAPI 极简 Web UI 入口。"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许以 `python -m src.main` 或 `uvicorn src.main:app` 从仓库根运行
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.agent import run_assistant
from src.config import MOCK_TODAY, MOCK_TOMORROW, STATIC_DIR, require_openai_api_key


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        require_openai_api_key()
        print("[OK] OPENAI_API_KEY loaded")
    except RuntimeError as exc:
        print(f"[WARN] {exc}")
        print("  Server started, but /api/chat returns 503 until a valid key is set.")
    yield


app = FastAPI(
    title="Personal AI Assistant — Baseline v1",
    version="0.1.0",
    lifespan=lifespan,
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户自然语言输入")


class ChatResponse(BaseModel):
    reply: str
    tools_called: list[str]
    mock_today: str = MOCK_TODAY
    mock_tomorrow: str = MOCK_TOMORROW


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    has_key = True
    try:
        require_openai_api_key()
    except RuntimeError:
        has_key = False
    return {
        "ok": True,
        "has_openai_api_key": has_key,
        "mock_today": MOCK_TODAY,
        "mock_tomorrow": MOCK_TOMORROW,
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

    try:
        result = await run_assistant(message)
    except Exception as exc:  # noqa: BLE001 — 演示用：把上游错误清晰返回
        raise HTTPException(status_code=500, detail=f"助手运行失败: {exc}") from exc

    return ChatResponse(
        reply=result["reply"],
        tools_called=result["tools_called"],
    )


# 静态资源（CSS/JS 若后续拆分）
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run("src.main:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
