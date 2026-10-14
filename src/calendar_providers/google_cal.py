"""Google Calendar 只读 provider（OAuth Desktop）。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.calendar_providers.common import TimeOfDay, in_time_of_day, normalize_event
from src.config import (
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_TOKEN_PATH,
    get_google_calendar_id,
)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class GoogleCalendarProvider:
    name = "google"

    def query_events(self, date: str, time_of_day: TimeOfDay | str = "all") -> dict[str, Any]:
        service = _build_service()
        calendars = _resolve_calendars(service, get_google_calendar_id())
        day_start = datetime.fromisoformat(f"{date}T00:00:00").astimezone()
        day_end = day_start + timedelta(days=1)

        events: list[dict[str, Any]] = []
        for cal in calendars:
            response = (
                service.events()
                .list(
                    calendarId=cal["id"],
                    timeMin=day_start.isoformat(),
                    timeMax=day_end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                )
                .execute()
            )
            for item in response.get("items") or []:
                start = _event_datetime(item.get("start") or {})
                end = _event_datetime(item.get("end") or {})
                if not start:
                    continue
                if not in_time_of_day(start, time_of_day):
                    continue
                event = normalize_event(
                    {
                        "id": item.get("id"),
                        "title": item.get("summary") or "(no title)",
                        "start": start,
                        "end": end,
                        "location": item.get("location"),
                        "notes": item.get("description"),
                    }
                )
                event["calendar"] = cal["summary"]
                events.append(event)

        events.sort(key=lambda e: e.get("start") or "")
        return {
            "source": self.name,
            "calendars": [c["summary"] for c in calendars],
            "date": date,
            "time_of_day": time_of_day,
            "events": events,
        }


def _resolve_calendars(service, setting: str) -> list[dict[str, str]]:
    """解析要查询的日历列表。

    - selected / all：Google 界面里勾选的日历（含导入课表）
    - primary：仅主日历
    - 其他：当作单个 calendarId
    """
    value = (setting or "selected").strip().lower()
    listed = service.calendarList().list().execute().get("items") or []

    if value in {"selected", "all"}:
        chosen = []
        for item in listed:
            # selected=True 对应网页勾选；primary 始终纳入
            if item.get("selected") or item.get("primary"):
                chosen.append(
                    {
                        "id": str(item["id"]),
                        "summary": str(item.get("summary") or item["id"]),
                    }
                )
        if chosen:
            return chosen
        # 兜底：至少主日历
        return [{"id": "primary", "summary": "primary"}]

    if value == "primary":
        primary = next((i for i in listed if i.get("primary")), None)
        summary = str(primary.get("summary") or "primary") if primary else "primary"
        return [{"id": "primary", "summary": summary}]

    match = next((i for i in listed if i.get("id") == setting), None)
    summary = str(match.get("summary") or setting) if match else setting
    return [{"id": setting, "summary": summary}]


def _event_datetime(payload: dict[str, Any]) -> str | None:
    if payload.get("dateTime"):
        return str(payload["dateTime"])
    if payload.get("date"):
        # 全天事件：用当天 00:00 本地表示，便于时段过滤
        return f"{payload['date']}T00:00:00"
    return None


def _build_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google Calendar 依赖未安装。请运行: pip install -r requirements.txt"
        ) from exc

    if not GOOGLE_CREDENTIALS_PATH.is_file():
        raise RuntimeError(
            f"缺少 Google OAuth 客户端文件: {GOOGLE_CREDENTIALS_PATH}\n"
            "请按 docs/google-calendar-setup.md 创建 Desktop OAuth 客户端，"
            "并将 credentials.json 放到 secrets/ 目录。"
        )

    creds = None
    if GOOGLE_TOKEN_PATH.is_file():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GOOGLE_CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
        GOOGLE_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def ensure_google_login() -> str:
    """触发一次 OAuth（供 scripts/auth_google_calendar.py 使用）。"""
    _build_service()
    return f"Google Calendar authorized. Token saved to {GOOGLE_TOKEN_PATH}"
