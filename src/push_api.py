"""「来找你」的接口：订阅设备、试推一条、他点开了哪条；以及服务端定时器。"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src import nudges, push, usage_log, webpush
from src.config import STATIC_DIR, get_calendar_backend

router = APIRouter(tags=["push"])
TICK_S = 60


class SubscribeBody(BaseModel):
    subscription: dict[str, Any]
    device: str = Field("", max_length=200)


class EndpointBody(BaseModel):
    endpoint: str


class OpenedBody(BaseModel):
    key: str = Field(..., max_length=200)


@router.get("/sw.js")
def service_worker() -> FileResponse:
    # 放在根路径：作用域才能覆盖整个页面
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/api/push/key")
def push_key() -> dict:
    return {"public_key": webpush.vapid_public_key(), "devices": len(push.devices())}


@router.post("/api/push/subscribe")
def push_subscribe(body: SubscribeBody) -> dict:
    try:
        count = push.subscribe(body.subscription, body.device)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "devices": count}


@router.post("/api/push/unsubscribe")
def push_unsubscribe(body: EndpointBody) -> dict:
    push.unsubscribe(body.endpoint)
    return {"ok": True}


@router.post("/api/push/test")
def push_test() -> dict:
    delivered = push.deliver({"title": "Friday", "body": "这样我就能来找你了。", "url": "/", "tag": "test"})
    return {"ok": delivered > 0, "delivered": delivered}


@router.post("/api/nudges/opened")
def nudge_opened(body: OpenedBody) -> dict:
    """他从通知点进来了：「来找你」值不值，就看点开的比例。"""
    usage_log.record("nudge_open", ok=True, first_token_ms=None, total_ms=0, tools=[body.key.split(":")[0]])
    return {"ok": True}


@router.get("/api/nudges")
def nudge_history(days: int = 7) -> dict:
    return {"sent": nudges.history(max(1, min(days, 30))), "devices": len(push.devices())}


def scheduler_enabled() -> bool:
    """云上默认开（只有一台机器）；本机默认关，免得和云上各发一遍。FRIDAY_NUDGES=on/off 可强制。"""
    flag = (os.getenv("FRIDAY_NUDGES") or "").strip().lower()
    if flag in {"on", "1", "true"}:
        return True
    if flag in {"off", "0", "false"}:
        return False
    try:
        real_calendar = get_calendar_backend() == "google"
    except RuntimeError:
        real_calendar = False
    return bool(os.getenv("FLY_APP_NAME")) and real_calendar


async def run_scheduler() -> None:
    while True:
        try:
            sent = await asyncio.to_thread(nudges.tick)
            for nudge in sent:
                print(f"[OK] nudge sent: {nudge['key']}")
        except Exception as exc:  # noqa: BLE001 — 定时器不能因为一次出错就停
            print(f"[WARN] nudge tick failed: {exc}")
        await asyncio.sleep(TICK_S)
