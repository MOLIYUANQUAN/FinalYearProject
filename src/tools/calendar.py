"""日历工具：按配置走 mock 或 Google 只读 provider。"""

from __future__ import annotations

from typing import Any

from agents import function_tool

from src.calendar_providers import get_calendar_provider
from src.calendar_providers.common import TimeOfDay


def query_calendar_events(
    date: str,
    time_of_day: TimeOfDay = "all",
) -> dict[str, Any]:
    """按日期查询日历事件（纯函数，供测试与工具共用）。"""
    provider = get_calendar_provider()
    return provider.query_events(date=date, time_of_day=time_of_day)


@function_tool
def get_calendar_events(
    date: str,
    time_of_day: TimeOfDay = "all",
) -> dict[str, Any]:
    """按日期查询日历事件（mock 本地 JSON，或 Google Calendar 只读）。

    Args:
        date: 具体日期，格式 YYYY-MM-DD（例如 2026-10-13）。相对词如「明天」须先解析成该格式。
        time_of_day: 可选时段过滤：morning / afternoon / evening / all。
    """
    return query_calendar_events(date=date, time_of_day=time_of_day)
