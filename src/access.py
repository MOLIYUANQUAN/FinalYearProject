"""外网进 Friday 要访问码；没设 FRIDAY_ACCESS_TOKEN 时和现在一样，不拦。"""

from __future__ import annotations

import hmac
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config import get_access_token

# 静态页和首页可以先出来，好输入访问码；健康检查给负载均衡（不含对话）
PUBLIC_PREFIXES = ("/static/",)
PUBLIC_PATHS = {"/", "/favicon.ico", "/static/manifest.json", "/api/health"}


def _offered(request: Request) -> str:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.query_params.get("access") or "").strip()


def authorized(request: Request) -> bool:
    expected = get_access_token()
    if not expected:
        return True
    offered = _offered(request)
    return bool(offered) and hmac.compare_digest(offered, expected)


async def gate(request: Request, call_next: Any) -> Response:
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)
    if path == "/manifest.json" or path.endswith("manifest.json"):
        return await call_next(request)
    if authorized(request):
        return await call_next(request)
    return JSONResponse(
        {"detail": "需要访问码：用带 ?access=… 的链接打开，或在本页输入。"},
        status_code=401,
    )
