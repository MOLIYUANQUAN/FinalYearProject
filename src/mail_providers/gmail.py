"""Gmail 读写（复用 Google OAuth Desktop 客户端）。"""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from typing import Any

from src.config import GOOGLE_CREDENTIALS_PATH, GMAIL_TOKEN_PATH

# modify: 读/改标签/草稿等；send: 发送
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailMailProvider:
    name = "gmail"

    def search_messages(self, query: str, top: int = 5) -> dict[str, Any]:
        service = _build_service()
        top = max(1, min(int(top), 20))
        q = (query or "").strip() or "in:inbox"
        try:
            listed = (
                service.users()
                .messages()
                .list(userId="me", q=q, maxResults=top)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "source": self.name,
                "error": "gmail_list_failed",
                "message": str(exc),
                "messages": [],
            }

        messages = []
        for item in listed.get("messages") or []:
            mid = item.get("id")
            if not mid:
                continue
            meta = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in (meta.get("payload") or {}).get("headers") or []
                if "name" in h and "value" in h
            }
            messages.append(
                {
                    "id": mid,
                    "subject": headers.get("subject") or "(no subject)",
                    "from": headers.get("from") or "",
                    "received": headers.get("date") or "",
                    "body_preview": (meta.get("snippet") or "")[:240],
                    "label_ids": meta.get("labelIds") or [],
                }
            )

        return {
            "ok": True,
            "source": self.name,
            "query": query,
            "messages": messages,
        }

    def get_message(self, message_id: str) -> dict[str, Any]:
        service = _build_service()
        try:
            raw = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "source": self.name,
                "error": "gmail_get_failed",
                "message": str(exc),
            }

        headers = {
            h["name"].lower(): h["value"]
            for h in (raw.get("payload") or {}).get("headers") or []
            if "name" in h and "value" in h
        }
        body = _extract_body(raw.get("payload") or {})
        if len(body) > 4000:
            body = body[:4000] + "\n...[truncated]"

        return {
            "ok": True,
            "source": self.name,
            "message": {
                "id": raw.get("id"),
                "thread_id": raw.get("threadId"),
                "subject": headers.get("subject") or "(no subject)",
                "from": headers.get("from") or "",
                "received": headers.get("date") or "",
                "body_preview": (raw.get("snippet") or "")[:240],
                "body": body or (raw.get("snippet") or ""),
                "label_ids": raw.get("labelIds") or [],
            },
        }

    def send_message(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
    ) -> dict[str, Any]:
        service = _build_service()
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        try:
            sent = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "source": self.name,
                "error": "gmail_send_failed",
                "message": str(exc),
            }
        return {
            "ok": True,
            "source": self.name,
            "id": sent.get("id"),
            "thread_id": sent.get("threadId"),
            "to": to,
            "subject": subject,
        }

    def modify_labels(
        self,
        *,
        message_id: str,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        service = _build_service()
        body = {
            "addLabelIds": add_labels or [],
            "removeLabelIds": remove_labels or [],
        }
        try:
            updated = (
                service.users()
                .messages()
                .modify(userId="me", id=message_id, body=body)
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "source": self.name,
                "error": "gmail_modify_failed",
                "message": str(exc),
            }
        return {
            "ok": True,
            "source": self.name,
            "id": updated.get("id"),
            "label_ids": updated.get("labelIds") or [],
        }


def _extract_body(payload: dict[str, Any]) -> str:
    mime = (payload.get("mimeType") or "").lower()
    data = (payload.get("body") or {}).get("data")
    if data and mime.startswith("text/plain"):
        return _b64(data)
    if data and mime.startswith("text/html"):
        return _strip_html(_b64(data))

    for part in payload.get("parts") or []:
        text = _extract_body(part)
        if text:
            return text
    if data:
        return _b64(data)
    return ""


def _b64(data: str) -> str:
    raw = base64.urlsafe_b64decode(data.encode("utf-8"))
    return raw.decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?(</\1>)", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _scopes_sufficient(creds) -> bool:
    granted = set(creds.scopes or [])
    return set(SCOPES).issubset(granted)


def _build_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google 依赖未安装。请运行: pip install -r requirements.txt"
        ) from exc

    if not GOOGLE_CREDENTIALS_PATH.is_file():
        raise RuntimeError(
            f"缺少 Google OAuth 客户端: {GOOGLE_CREDENTIALS_PATH}\n"
            "可复用日历同一套 secrets/credentials.json。"
            "并在 Google Cloud 启用 Gmail API。"
        )

    creds = None
    if GMAIL_TOKEN_PATH.is_file():
        creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_PATH), SCOPES)
        if creds and not _scopes_sufficient(creds):
            creds = None
            GMAIL_TOKEN_PATH.unlink(missing_ok=True)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token and _scopes_sufficient(creds):
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GOOGLE_CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0, prompt="consent")
        GMAIL_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GMAIL_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def ensure_gmail_login() -> str:
    _build_service()
    return f"Gmail authorized (read/modify/send). Token saved to {GMAIL_TOKEN_PATH}"
