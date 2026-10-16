"""日历工具：查询 +（确认后）创建事件。"""

from __future__ import annotations

from typing import Any

from agents import function_tool

from src import agenda
from src.calendar_providers import get_calendar_provider
from src.calendar_providers.common import TimeOfDay, is_background_span

MAX_DAYS = 14


def query_calendar_events(
    date: str,
    time_of_day: TimeOfDay = "all",
    days: int = 1,
) -> dict[str, Any]:
    """按日期查询日历事件（纯函数，供测试与工具共用）。"""
    provider = get_calendar_provider()
    result = provider.query_events(
        date=date,
        time_of_day=time_of_day,
        days=min(max(days, 1), MAX_DAYS),
    )
    events = list(result.get("events") or [])
    background = [e for e in events if is_background_span(e)]
    if background:
        result["events"] = [e for e in events if not is_background_span(e)]
        result["background"] = sorted({str(e.get("title")) for e in background})
    return result


@function_tool
def get_calendar_events(
    date: str,
    time_of_day: TimeOfDay = "all",
    days: int = 1,
) -> dict[str, Any]:
    """读他的日历（含导入的大学课表）。

    返回里的 background 是跨多天的背景（如教学周期、学期），不是那几天的具体安排；他没问起就别提。

    Args:
        date: 起始日期，格式 YYYY-MM-DD（例如 2026-10-13）。「明天」「周一」这类说法先换算成具体日期。
        time_of_day: 可选时段过滤：morning / afternoon / evening / all。
        days: 连续看几天（1–14）。问「这周还有什么」就从今天看到周日，一次查完。
    """
    return query_calendar_events(date=date, time_of_day=time_of_day, days=days)


@function_tool
def create_calendar_event(
    title: str,
    start: str,
    end: str,
    location: str = "",
    notes: str = "",
    user_confirmed: bool = False,
) -> dict[str, Any]:
    """在日历中创建事件。必须先 request_user_confirmation，且仅当用户明确同意后
    才能以 user_confirmed=True 调用。

    Args:
        title: 事件标题。
        start: 开始时间 ISO，建议 YYYY-MM-DDTHH:MM（欧洲/伦敦本地）。
        end: 结束时间 ISO，建议 YYYY-MM-DDTHH:MM。
        location: 可选地点。
        notes: 可选备注。
        user_confirmed: 用户是否已在本对话中明确确认创建。未确认必须为 False。
    """
    if not user_confirmed:
        return {
            "ok": False,
            "error": "user_not_confirmed",
            "message": (
                "尚未获得用户确认。请先调用 request_user_confirmation，"
                "向用户展示计划，待用户明确同意后再以 user_confirmed=True 调用。"
            ),
        }

    provider = get_calendar_provider()
    create = getattr(provider, "create_event", None)
    if create is None:
        return {"ok": False, "error": "create_not_supported"}

    try:
        created = create(
            title=title,
            start=start,
            end=end,
            location=location or None,
            notes=notes or None,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "create_failed", "message": str(exc)}
    agenda.forget()
    return created
