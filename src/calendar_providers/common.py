"""日历查询共用的时段过滤与事件整形。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal

TimeOfDay = Literal["morning", "afternoon", "evening", "all"]


def hour_from_iso(iso: str) -> int:
    # 支持带 Z / 偏移的 ISO；取本地展示用的小时
    normalized = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).hour


def in_time_of_day(start_iso: str, time_of_day: TimeOfDay | str) -> bool:
    if time_of_day == "all":
        return True
    hour = hour_from_iso(start_iso)
    if time_of_day == "morning":
        return 5 <= hour < 12
    if time_of_day == "afternoon":
        return 12 <= hour < 17
    if time_of_day == "evening":
        return 17 <= hour < 24 or hour < 5
    return True


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "id": event.get("id"),
        "title": event.get("title"),
        "start": event.get("start"),
        "end": event.get("end"),
        "location": event.get("location"),
        "notes": event.get("notes"),
    }
    if event.get("all_day"):
        normalized["all_day"] = True
    return normalized


def range_end(start_date: str, days: int) -> str:
    """[start_date, range_end) 的右端，YYYY-MM-DD。"""
    return (date.fromisoformat(start_date) + timedelta(days=days)).isoformat()


def is_background_span(event: dict[str, Any]) -> bool:
    """跨多天的全天事件（教学周期、学期）只是背景，不是某一天的安排。"""
    if not event.get("all_day"):
        return False
    try:
        start = date.fromisoformat(str(event.get("start"))[:10])
        end = date.fromisoformat(str(event.get("end"))[:10])
    except ValueError:
        return False
    return end - start > timedelta(days=1)
