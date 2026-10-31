"""她的资料页（像 WhatsApp 点联系人名字）：这个月的用量、她现在用的是谁、连接、推送设置、她记得的事。

数字都在服务端算好，页面只管显示。能改的只有三样：每天最多几条推送、安静时段、删掉她记得的某件事。
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as Timeout
from datetime import datetime
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src import agenda, claude, ledger, memory_store, push, settings, todos, usage_log, voice
from src.agent import active_model, answering_model
from src.config import USAGE_LOG_PATH, effective_now, get_calendar_backend
from src.mail_providers import label_of, mailboxes

router = APIRouter(tags=["about"])
CHECK_TIMEOUT_S = 6
_RELOGIN = "要重新登录 Google：在电脑上运行 scripts/google_login.py"


def _check(name: str, read: Callable[[], Any]) -> dict[str, Any]:
    """读一次：成了就是正常；Google 的登录过期了就直说怎么修。"""
    try:
        result = read()
        problem = result.get("message") or result.get("error") if isinstance(result, dict) and result.get("ok") is False else ""
    except Exception as exc:  # noqa: BLE001
        problem = str(exc)
    if not problem:
        return {"name": name, "ok": True, "note": "正常"}
    lowered = problem.lower()
    expired = any(word in lowered for word in ("invalid_grant", "expired", "revoked", "unauthorized", "401"))
    return {"name": name, "ok": False, "note": _RELOGIN if expired else problem.splitlines()[0][:80]}


def connections() -> list[dict[str, Any]]:
    checks: list[tuple[str, Callable[[], Any]]] = []
    try:
        if get_calendar_backend() != "none":
            checks.append(("日历", agenda.read))
    except RuntimeError:
        pass
    try:
        for box in mailboxes():  # 每个邮箱一行：Gmail、163 邮箱……
            checks.append((label_of(box), lambda box=box: box.search_messages("in:inbox", 1)))
    except RuntimeError:
        pass
    if todos.connected():
        checks.append(("待办", todos.read))
    pool = ThreadPoolExecutor(max_workers=max(1, len(checks)))
    futures = [(name, pool.submit(_check, name, read)) for name, read in checks]
    out = []
    deadline = time.monotonic() + CHECK_TIMEOUT_S
    for name, future in futures:
        try:
            out.append(future.result(timeout=max(0.0, deadline - time.monotonic())))
        except Timeout:
            out.append({"name": name, "ok": False, "note": "这次没读到，过会儿再看"})
    # 卡住的那个不等它：页面先出来（with 块退出时会等所有线程，所以不用 with）
    pool.shutdown(wait=False, cancel_futures=True)
    issue = claude.issue()
    if active_model().startswith("claude"):
        out.insert(0, {"name": "Claude", "ok": not issue, "note": issue or "正常"})
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        out.append({"name": "语音（OpenAI）", "ok": False, "note": "没有 OpenAI key，按住说话用不了"})
    elif voice.live_problem():
        out.append({"name": "语音（OpenAI）", "ok": False,
                    "note": f"边说边出字没连上，松手后照常转写：{voice.live_problem()}"})
    else:
        out.append({"name": "语音（OpenAI）", "ok": True, "note": "正常"})
    return out


def _today(now: datetime) -> dict[str, Any]:
    """今天说了几句、平均多久开始回答（从使用记录里数）。"""
    day = now.date().isoformat()
    turns, waits = 0, []
    if USAGE_LOG_PATH.is_file():
        for line in USAGE_LOG_PATH.read_text(encoding="utf-8").splitlines():
            row = usage_log.parse(line)
            if not row or not str(row.get("ts", "")).startswith(day) or row.get("kind") not in ("chat", "voice"):
                continue
            turns += 1
            if row.get("first_token_ms"):
                waits.append(int(row["first_token_ms"]))
    return {"turns": turns, "first_reply_s": round(sum(waits) / len(waits) / 1000, 1) if waits else None}


@router.get("/api/me")
def me() -> dict[str, Any]:
    now = effective_now()
    answering = answering_model()
    return {
        "model": ledger.label(answering),
        "backup": answering != active_model() or not active_model().startswith("claude"),
        "issue": claude.issue(),
        "usage": {**ledger.month(), "today": _today(now), "admin_key": bool((os.getenv("ANTHROPIC_ADMIN_KEY") or "").strip())},
        "connections": connections(),
        "push": {"devices": len(push.devices()), **settings.get()},
        "memory": len(memory_store.all_facts()),
        "version": (os.getenv("FRIDAY_GIT_SHA") or "")[:7],
    }


class SettingsBody(BaseModel):
    daily_max: int | None = Field(None, ge=0, le=10)
    quiet_from: str | None = Field(None, max_length=5)
    quiet_until: str | None = Field(None, max_length=5)


@router.post("/api/settings")
def save_settings(body: SettingsBody) -> dict[str, Any]:
    try:
        return settings.update(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/memory")
def memories() -> list[dict[str, Any]]:
    """她记得的事，最近的在前。"""
    return [
        {"id": f["id"], "content": f.get("content", ""), "at": (f.get("updated_at") or f.get("created_at") or "")[:10], "fact": f}
        for f in memory_store.all_facts()
        if f.get("id")
    ]


@router.delete("/api/memory/{fact_id}")
def forget(fact_id: str) -> dict[str, Any]:
    """他自己点的删除：直接删，给撤销（不走她动手前要他确认那一套）。"""
    fact = next((f for f in memory_store.all_facts() if f.get("id") == fact_id), None)
    if fact is None:
        raise HTTPException(status_code=404, detail="这条已经不在了。")
    memory_store.forget_fact(fact_id)
    return {"ok": True, "fact": fact}


class RestoreBody(BaseModel):
    fact: dict[str, Any]


@router.post("/api/memory/restore")
def restore(body: RestoreBody) -> dict[str, Any]:
    if not body.fact.get("id") or not str(body.fact.get("content") or "").strip():
        raise HTTPException(status_code=400, detail="这条撤销不了。")
    memory_store.merge_facts([body.fact])
    return {"ok": True}
