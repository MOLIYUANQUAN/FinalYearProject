"""本地 JSON mock 日历（Baseline 默认）。"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from src.calendar_providers.common import TimeOfDay, in_time_of_day, normalize_event
from src.config import CALENDAR_PATH


class MockCalendarProvider:
    name = "mock"

    def query_events(self, date: str, time_of_day: TimeOfDay | str = "all") -> dict[str, Any]:
        raw_events = _load_raw_events()

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

    def create_event(
        self,
        *,
        title: str,
        start: str,
        end: str,
        location: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        data = {"events": _load_raw_events()}
        event = {
            "id": f"evt-{uuid4().hex[:8]}",
            "title": title,
            "start": start,
            "end": end,
            "location": location,
            "notes": notes,
        }
        data["events"].append(event)
        CALENDAR_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "ok": True,
            "source": self.name,
            "calendar_id": "mock",
            "id": event["id"],
            "title": title,
            "start": start,
            "end": end,
            "html_link": None,
        }


def _load_raw_events() -> list[dict[str, Any]]:
    with CALENDAR_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("events") or [])
