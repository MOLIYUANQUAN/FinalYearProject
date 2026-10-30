"""随手交给 Friday：「嘿 Siri，告诉 Friday……」、分享菜单、快捷指令。

iPhone 快捷指令把一句话 POST 到 /api/capture，Friday 在当前对话里办，回一段能直接念出来的话（纯文本）。
用一把单独的令牌（STATE_DIR/capture_token），只能调这一个接口；不放心了在设置页换一把。
"""

from __future__ import annotations

import json
import re
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from src import usage_log
from src.agent import friday
from src.config import STATE_DIR, STATIC_DIR

router = APIRouter(tags=["capture"])
TOKEN_PATH = STATE_DIR / "capture_token.json"
MAX_CHARS = 2000


def _load() -> dict[str, Any]:
    if TOKEN_PATH.is_file():
        try:
            return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save(data: dict[str, Any]) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(data), encoding="utf-8")


def token(*, rotate: bool = False) -> str:
    data = _load()
    if rotate or not data.get("token"):
        data = {"token": secrets.token_urlsafe(24), "created_at": int(time.time())}
        _save(data)
    return data["token"]


def capture_authorized(request: Request) -> bool:
    """/api/capture 只认这把快捷指令令牌（access.gate 里用）。"""
    stored = _load().get("token")
    auth = request.headers.get("authorization") or ""
    offered = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    return bool(stored and offered and secrets.compare_digest(offered, stored))


def _base_url(request: Request) -> str:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    return f"{proto}://{request.headers.get('host') or request.url.netloc}"


def _speakable(text: str) -> str:
    """念出来的话：去掉 Markdown 记号和链接。"""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*#`>_]+", "", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


@router.get("/siri")
def siri_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "siri.html", headers={"Cache-Control": "no-store"})


@router.get("/api/capture/setup")
def capture_setup(request: Request, rotate: bool = False) -> dict:
    """设置页用：快捷指令里要填的地址和令牌（要先登录 Friday 才拿得到）。"""
    data = _load()
    return {
        "url": f"{_base_url(request)}/api/capture",
        "token": token(rotate=rotate),
        "used_at": None if rotate else data.get("used_at"),
    }


@router.post("/api/capture")
async def capture(request: Request) -> PlainTextResponse:
    raw = (await request.body()).decode("utf-8", errors="replace").strip()
    text = raw
    if raw.startswith("{"):
        try:
            text = str(json.loads(raw).get("text") or "").strip()
        except (json.JSONDecodeError, AttributeError):
            text = raw
    if not text:
        raise HTTPException(status_code=400, detail="没听到内容。")
    text = text[:MAX_CHARS]

    started = time.perf_counter()
    cid = friday.resolve_conversation(None)
    done: dict[str, Any] = {}
    async for event in friday.turn(cid, text, spoken=True):
        if event["type"] == "done":
            done = event
    if done.get("needs_confirm"):
        # 卡片要他亲眼看了再点：念出来只说要做什么，不把整封邮件念一遍
        names = {a.get("name") for a in done.get("approvals") or []}
        what = "邮件写好了" if "send_email" in names else "要做的事准备好了"
        say = f"{what}，打开 Friday 看一眼，点确认就办。"
    else:
        say = _speakable(done.get("reply") or "") or "好。"

    data = _load()
    data["used_at"] = int(time.time())
    _save(data)
    usage_log.record("capture", ok=True, first_token_ms=None,
                     total_ms=int((time.perf_counter() - started) * 1000), tools=list(done.get("tools_called") or []))
    return PlainTextResponse(say)
