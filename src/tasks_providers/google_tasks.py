"""Google Tasks 的默认清单：他手机上的 Google Tasks 和日历里也看得到、会提醒。"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.config import GOOGLE_CREDENTIALS_PATH, GOOGLE_TASKS_TOKEN_PATH

SCOPES = ["https://www.googleapis.com/auth/tasks"]
SIGN_IN_AGAIN = "Google 登录过期了：在电脑上运行 scripts\\google_login.py，日历、待办、邮件一次登好。"
LIST = "@default"


def _due(day: date) -> str:
    return f"{day.isoformat()}T00:00:00.000Z"


def _task(item: dict[str, Any]) -> dict[str, Any]:
    # Google Tasks 的截止只记日期（时间部分会被丢掉）：直接取日期，不做时区换算
    return {
        "id": item.get("id"),
        "title": (item.get("title") or "").strip() or "（无标题）",
        "due": str(item.get("due") or "")[:10] or None,
        "notes": item.get("notes"),
    }


class GoogleTasksProvider:
    name = "google"

    def list_open(self) -> list[dict[str, Any]]:
        service = _build_service()
        tasks: list[dict[str, Any]] = []
        page_token = None
        while True:
            page = (
                service.tasks()
                .list(tasklist=LIST, showCompleted=False, showHidden=False, maxResults=100, pageToken=page_token)
                .execute()
            )
            tasks += [_task(item) for item in page.get("items") or [] if (item.get("title") or "").strip()]
            page_token = page.get("nextPageToken")
            if not page_token:
                return tasks

    def add(self, title: str, due: date | None, notes: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {"title": title}
        if due:
            body["due"] = _due(due)
        if notes:
            body["notes"] = notes
        return _task(_build_service().tasks().insert(tasklist=LIST, body=body).execute())

    def set_due(self, task_id: str, due: date | None) -> dict[str, Any]:
        body = {"due": _due(due) if due else None}
        return _task(_build_service().tasks().patch(tasklist=LIST, task=task_id, body=body).execute())

    def complete(self, task_id: str) -> dict[str, Any]:
        body = {"status": "completed"}
        return _task(_build_service().tasks().patch(tasklist=LIST, task=task_id, body=body).execute())

    def reopen(self, task_id: str) -> dict[str, Any]:
        body = {"status": "needsAction", "completed": None}
        return _task(_build_service().tasks().patch(tasklist=LIST, task=task_id, body=body).execute())

    def delete(self, task_id: str) -> None:
        _build_service().tasks().delete(tasklist=LIST, task=task_id).execute()


def _build_service(*, interactive: bool = False):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    if not GOOGLE_CREDENTIALS_PATH.is_file():
        raise RuntimeError(f"缺少 Google OAuth 客户端文件：{GOOGLE_CREDENTIALS_PATH}（见 docs/google-calendar-setup.md）")

    creds = None
    if GOOGLE_TASKS_TOKEN_PATH.is_file():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TASKS_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except RefreshError:
                pass
        if not refreshed:
            if not interactive:
                # 服务在后台跑：绝不突然弹出授权页，只告诉他怎么登录
                raise RuntimeError(SIGN_IN_AGAIN)
            flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
        GOOGLE_TASKS_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOOGLE_TASKS_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("tasks", "v1", credentials=creds, cache_discovery=False)


def ensure_tasks_login() -> str:
    _build_service(interactive=True)
    return f"Google Tasks authorized. Token saved to {GOOGLE_TASKS_TOKEN_PATH}"
