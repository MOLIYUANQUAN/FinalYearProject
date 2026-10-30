"""一个大脑：本机攒下的记忆和摩擦清单搬到云上；使用记录从云上读回来看。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src import friction, memory_store
from src.config import USAGE_LOG_PATH

router = APIRouter(tags=["state"])


class StateImport(BaseModel):
    facts: list[dict[str, Any]] = Field(default_factory=list)
    friction: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/api/state/import")
def import_state(body: StateImport) -> dict:
    """合并，不覆盖：重复跑也安全。"""
    return {
        "ok": True,
        "facts": memory_store.merge_facts(body.facts),
        "friction": friction.merge_items(body.friction),
    }


@router.get("/api/state/export")
def export_state() -> dict:
    """整份记忆和摩擦清单，用来备份或搬家。"""
    return {"facts": memory_store.all_facts(), "friction": friction.all_items()}


@router.get("/api/usage/events")
def usage_events(days: int = 7) -> dict:
    """最近几天的使用记录（只有元数据，没有对话内容），给 usage_report --remote 用。"""
    since = (date.today() - timedelta(days=max(1, min(days, 90)) - 1)).isoformat()
    events = []
    if USAGE_LOG_PATH.is_file():
        for line in USAGE_LOG_PATH.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(entry.get("ts", ""))[:10] >= since:
                events.append(entry)
    return {"events": events}
