"""日历数据源：mock（演示）或 google（真实日历）。"""

from __future__ import annotations

from typing import Any, Protocol

from src.config import get_calendar_backend


class CalendarProvider(Protocol):
    name: str

    def query_events(
        self, date: str, time_of_day: str = "all", days: int = 1
    ) -> dict[str, Any]:
        ...


def get_calendar_provider() -> CalendarProvider:
    backend = get_calendar_backend()
    if backend == "google":
        from src.calendar_providers.google_cal import GoogleCalendarProvider

        return GoogleCalendarProvider()
    from src.calendar_providers.mock import MockCalendarProvider

    return MockCalendarProvider()


__all__ = ["CalendarProvider", "get_calendar_provider"]
