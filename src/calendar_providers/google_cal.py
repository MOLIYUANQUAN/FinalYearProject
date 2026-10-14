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
        calendar_id = get_google_calendar_id()
        day_start = datetime.fromisoformat(f"{date}T00:00:00").astimezone()
        day_end = day_start + timedelta(days=1)

        response = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
            )
            .execute()
        )

        events = []
        for item in response.get("items") or []:
            start = _event_datetime(item.get("start") or {})
            end = _event_datetime(item.get("end") or {})
            if not start:
                continue
            if not in_time_of_day(start, time_of_day):
                continue
            events.append(
                normalize_event(
                    {
                        "id": item.get("id"),
                        "title": item.get("summary") or "(no title)",
                        "start": start,
                        "end": end,
                        "location": item.get("location"),
                        "notes": item.get("description"),
                    }
                )
            )

        return {
            "source": self.name,
            "calendar_id": calendar_id,
            "date": date,
            "time_of_day": time_of_day,
            "events": events,
        }


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
