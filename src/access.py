"""外网进 Friday：密码换会话 Cookie；没设 FRIDAY_ACCESS_TOKEN 时不拦（只适合本机）。"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config import get_access_token

# 静态页和首页可以先出来，好输入密码；时钟探活公开（不含对话）
PUBLIC_PREFIXES = ("/static/",)
PUBLIC_PATHS = {
    "/",
    "/favicon.ico",
    "/static/manifest.json",
    "/api/health",
    "/api/login",
    "/api/logout",
    "/api/session",
    "/sw.js",  # Service Worker 脚本本身不含数据；推送、订阅接口仍要登录
    "/privacy",  # Google OAuth 发布为正式版要一个公开的隐私政策页
}

COOKIE_NAME = "friday_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 天
_SESSION_MSG = b"friday.session.v1"

router = APIRouter(tags=["auth"])


class LoginBody(BaseModel):
    password: str = Field(..., min_length=1)


def _session_value(secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), _SESSION_MSG, hashlib.sha256).hexdigest()


def _offered_bearer_or_query(request: Request) -> str:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.query_params.get("access") or "").strip()


def _cookie_ok(request: Request, expected: str) -> bool:
    offered = (request.cookies.get(COOKIE_NAME) or "").strip()
    if not offered:
        return False
    return hmac.compare_digest(offered, _session_value(expected))


def authorized(request: Request) -> bool:
    expected = get_access_token()
    if not expected:
        return True
    offered = _offered_bearer_or_query(request)
    if offered and hmac.compare_digest(offered, expected):
        return True
    return _cookie_ok(request, expected)


def _secure_cookie(request: Request) -> bool:
    if (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip() == "https":
        return True
    return request.url.scheme == "https"


def set_session_cookie(response: Response, request: Request, secret: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=_session_value(secret),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


async def gate(request: Request, call_next: Any) -> Response:
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)
    if path == "/manifest.json" or path.endswith("manifest.json"):
        return await call_next(request)
    if authorized(request):
        return await call_next(request)
    return JSONResponse(
        {"detail": "需要登录：在本页输入密码，或用桌面快捷方式打开。"},
        status_code=401,
    )


@router.post("/api/login")
async def login(body: LoginBody, request: Request) -> Response:
    expected = get_access_token()
    if not expected:
        return JSONResponse({"ok": True, "access_required": False})
    offered = body.password.strip()
    if not offered or not hmac.compare_digest(offered, expected):
        return JSONResponse({"detail": "密码不对。"}, status_code=401)
    response = JSONResponse({"ok": True, "access_required": True})
    set_session_cookie(response, request, expected)
    return response


@router.post("/api/logout")
async def logout() -> Response:
    response = JSONResponse({"ok": True})
    clear_session_cookie(response)
    return response


@router.get("/api/session")
async def session_status(request: Request) -> dict:
    """前端用来判断要不要显示解锁层（health 仍公开）。"""
    expected = get_access_token()
    if not expected:
        return {"access_required": False, "signed_in": True}
    return {"access_required": True, "signed_in": authorized(request)}
