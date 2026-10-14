"""本地 JSON mock 日历（Baseline 默认）。"""

from __future__ import annotations

import json
from typing import Any

from src.calendar_providers.common import TimeOfDay, in_time_of_day, normalize_event
from src.config import CALENDAR_PATH


class MockCalendarProvider:
    name = "mock"

    def query_events(self, date: str, time_of_day: TimeOfDay | str = "all") -> dict[str, Any]:
        with CALENDAR_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        raw_events = list(data.get("events") or [])

        events = []
        for event in raw_events:
            start = event.get("start") or ""
            if not start.startswith(date):
                continue
            if not in_time_of_day(start, time_of_day):
                continue
            events.append(normalize_event(event))

        events.sort(key=lambda e: e.get("start") or "")
        return {
            "source": self.name,
            "date": date,
            "time_of_day": time_of_day,
            "events": events,
        }
