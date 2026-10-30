"""Google Calendar provider（读 selected 日历 + 写 primary 事件）。"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from src.calendar_providers.common import TimeOfDay, in_time_of_day, normalize_event
from src.config import (
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_TOKEN_PATH,
    get_google_calendar_id,
)

# 读日历列表 + 读写事件；比旧版 readonly 更大，升级后需重新授权
SCOPES = ["https://www.googleapis.com/auth/calendar"]
SIGN_IN_AGAIN = "Google 日历需要重新登录：运行 scripts\\auth_google_calendar.py。"

# 日历列表几乎不变，每次都拉一遍要多等一个来回
CALENDAR_LIST_TTL_S = 600
_calendar_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}


def _local_tz():
    return datetime.now().astimezone().tzinfo


class GoogleCalendarProvider:
    name = "google"

    def query_events(
        self,
        date: str,
        time_of_day: TimeOfDay | str = "all",
        days: int = 1,
    ) -> dict[str, Any]:
        service = _build_service()
        calendars = _calendars(service)
        range_start = datetime.fromisoformat(f"{date}T00:00:00").replace(tzinfo=_local_tz())
        range_stop = range_start + timedelta(days=max(1, days))

        events: list[dict[str, Any]] = []
        for cal in calendars:
            response = (
                service.events()
                .list(
                    calendarId=cal["id"],
                    timeMin=range_start.isoformat(),
                    timeMax=range_stop.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
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
                        "all_day": "dateTime" not in (item.get("start") or {}),
                    }
                )
                event["calendar"] = cal["summary"]
                events.append(event)

        events.sort(key=lambda e: e.get("start") or "")
        return {
            "source": self.name,
            "calendars": [c["summary"] for c in calendars],
            "date": date,
            "days": max(1, days),
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
        """在主日历创建事件（写入只用 primary，避免改到导入课表）。"""
        service = _build_service()
        body: dict[str, Any] = {
            "summary": title,
            "start": _to_event_time(start),
            "end": _to_event_time(end),
        }
        if location:
            body["location"] = location
        if notes:
            body["description"] = notes

        created = (
            service.events()
            .insert(calendarId="primary", body=body)
            .execute()
        )
        return {
            "ok": True,
            "source": self.name,
            "calendar_id": "primary",
            "id": created.get("id"),
            "title": created.get("summary"),
            "start": _event_datetime(created.get("start") or {}),
            "end": _event_datetime(created.get("end") or {}),
            "html_link": created.get("htmlLink"),
        }


    def delete_event(self, event_id: str) -> None:
        """撤销 Friday 刚建的事件（只动 primary，导入的课表碰不到）。"""
        _build_service().events().delete(calendarId="primary", eventId=event_id).execute()


def _to_event_time(iso: str) -> dict[str, str]:
    """接受 YYYY-MM-DDTHH:MM 或带时区的 ISO，写成 Google dateTime。"""
    normalized = iso.strip().replace("Z", "+00:00")
    if len(normalized) == 16:  # YYYY-MM-DDTHH:MM
        normalized = normalized + ":00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_local_tz())
    return {"dateTime": dt.isoformat()}


def _calendars(service) -> list[dict[str, str]]:
    setting = get_google_calendar_id()
    cached = _calendar_cache.get(setting)
    if cached and time.monotonic() - cached[0] < CALENDAR_LIST_TTL_S:
        return cached[1]
    calendars = _resolve_calendars(service, setting)
    _calendar_cache[setting] = (time.monotonic(), calendars)
    return calendars


def _resolve_calendars(service, setting: str) -> list[dict[str, str]]:
    value = (setting or "selected").strip().lower()
    listed = service.calendarList().list().execute().get("items") or []

    if value in {"selected", "all"}:
        chosen = []
        for item in listed:
            if item.get("selected") or item.get("primary"):
                chosen.append(
                    {
                        "id": str(item["id"]),
                        "summary": str(item.get("summary") or item["id"]),
                    }
                )
        if chosen:
            return chosen
        return [{"id": "primary", "summary": "primary"}]

    if value == "primary":
        primary = next((i for i in listed if i.get("primary")), None)
        summary = str(primary.get("summary") or "primary") if primary else "primary"
        return [{"id": "primary", "summary": summary}]

    match = next((i for i in listed if i.get("id") == setting), None)
    summary = str(match.get("summary") or setting) if match else setting
    return [{"id": setting, "summary": summary}]


def _event_datetime(payload: dict[str, Any]) -> str | None:
    # 导入的课表给的是 UTC（…Z）：一律换成本地钟点，否则夏令时里每节课都早一小时
    if payload.get("dateTime"):
        moment = datetime.fromisoformat(str(payload["dateTime"]).replace("Z", "+00:00"))
        if moment.tzinfo is not None:
            moment = moment.astimezone().replace(tzinfo=None)
        return moment.isoformat(timespec="minutes")
    if payload.get("date"):
        return f"{payload['date']}T00:00:00"
    return None


def _scopes_sufficient(creds) -> bool:
    granted = set(creds.scopes or [])
    return set(SCOPES).issubset(granted)


def _build_service(*, interactive: bool = False):
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
        if creds and not _scopes_sufficient(creds):
            # 旧 token 只有 readonly，需要重新授权
            creds = None
            GOOGLE_TOKEN_PATH.unlink(missing_ok=True)

    if not creds or not creds.valid:
        if not _refresh(creds, Request):
            if not interactive:
                # 服务在后台跑：绝不突然弹出授权页，只告诉他怎么重新登录
                raise RuntimeError(SIGN_IN_AGAIN)
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GOOGLE_CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0, prompt="consent")
        GOOGLE_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _refresh(creds, request_class) -> bool:
    """用刷新令牌续上授权；令牌被撤销或过期（测试状态的应用 7 天就过期）时返回 False。"""
    from google.auth.exceptions import RefreshError

    if not (creds and creds.expired and creds.refresh_token):
        return False
    try:
        creds.refresh(request_class())
    except RefreshError:
        return False
    return True


def warm_up() -> None:
    """服务启动时先备好客户端和日历列表；只在已经授权过时做，绝不弹出授权页。"""
    if not GOOGLE_TOKEN_PATH.is_file():
        return
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), SCOPES)
    if not _scopes_sufficient(creds) or not (creds.valid or creds.refresh_token):
        return
    _calendars(_build_service())


def ensure_google_login() -> str:
    """触发一次 OAuth（读写事件权限）。"""
    _build_service(interactive=True)
    return (
        f"Google Calendar authorized (events read/write). Token saved to {GOOGLE_TOKEN_PATH}"
    )
