"""本地日历工具：读取 data/calendar.json。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from agents import function_tool

from src.config import CALENDAR_PATH

TimeOfDay = Literal["morning", "afternoon", "evening", "all"]


def _load_events() -> list[dict[str, Any]]:
    with CALENDAR_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("events") or [])


def _hour(iso: str) -> int:
    return datetime.fromisoformat(iso).hour


def _in_time_of_day(start_iso: str, time_of_day: TimeOfDay) -> bool:
    if time_of_day == "all":
        return True
    hour = _hour(start_iso)
    if time_of_day == "morning":
        return 5 <= hour < 12
    if time_of_day == "afternoon":
        return 12 <= hour < 17
    if time_of_day == "evening":
        return 17 <= hour < 24 or hour < 5
    return True


def query_calendar_events(
    date: str,
    time_of_day: TimeOfDay = "all",
) -> dict[str, Any]:
    """按日期查询本地日历事件（纯函数，供测试与工具共用）。"""
    events = []
    for event in _load_events():
        start = event.get("start") or ""
        if not start.startswith(date):
            continue
        if not _in_time_of_day(start, time_of_day):
            continue
        events.append(
            {
                "id": event.get("id"),
                "title": event.get("title"),
                "start": event.get("start"),
                "end": event.get("end"),
                "location": event.get("location"),
                "notes": event.get("notes"),
            }
        )
    events.sort(key=lambda e: e.get("start") or "")
    return {"date": date, "time_of_day": time_of_day, "events": events}


@function_tool
def get_calendar_events(
    date: str,
    time_of_day: TimeOfDay = "all",
) -> dict[str, Any]:
    """按日期查询本地日历事件。

    Args:
        date: 具体日期，格式 YYYY-MM-DD（例如 2026-10-13）。相对词如「明天」须先解析成该格式。
        time_of_day: 可选时段过滤：morning / afternoon / evening / all。
    """
    return query_calendar_events(date=date, time_of_day=time_of_day)
