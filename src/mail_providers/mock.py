"""本地 JSON mock 邮件。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.config import MAIL_MOCK_PATH


class MockMailProvider:
    name = "mock"

    def search_messages(self, query: str, top: int = 5) -> dict[str, Any]:
        q = (query or "").strip().lower()
        items = _load()
        if q:
            items = [
                m
                for m in items
                if q in (m.get("subject") or "").lower()
                or q in (m.get("from") or "").lower()
                or q in (m.get("body_preview") or "").lower()
                or q in (m.get("body") or "").lower()
            ]
        items = sorted(items, key=lambda m: m.get("received") or "", reverse=True)[
            : max(1, min(top, 20))
        ]
        return {
            "ok": True,
            "source": self.name,
            "query": query,
            "messages": [
                {
                    "id": m.get("id"),
                    "subject": m.get("subject"),
                    "from": m.get("from"),
                    "received": m.get("received"),
                    "body_preview": m.get("body_preview"),
                    "label_ids": m.get("label_ids") or ["INBOX"],
                }
                for m in items
            ],
        }

    def get_message(self, message_id: str) -> dict[str, Any]:
        for m in _load():
            if m.get("id") == message_id:
                return {"ok": True, "source": self.name, "message": m}
        return {
            "ok": False,
            "source": self.name,
            "error": "not_found",
            "message": f"找不到邮件: {message_id}",
        }

    def send_message(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
    ) -> dict[str, Any]:
        data = {"messages": _load()}
        mid = f"mock-sent-{uuid4().hex[:8]}"
        data["messages"].insert(
            0,
            {
                "id": mid,
                "subject": subject,
                "from": "me@mock.local",
                "to": to,
                "cc": cc,
                "received": datetime.now(timezone.utc).isoformat(),
                "body_preview": body[:120],
                "body": body,
                "label_ids": ["SENT"],
            },
        )
        _save(data)
        return {
            "ok": True,
            "source": self.name,
            "id": mid,
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
        data = {"messages": _load()}
        for m in data["messages"]:
            if m.get("id") != message_id:
                continue
            labels = set(m.get("label_ids") or ["INBOX"])
            labels.update(add_labels or [])
            labels.difference_update(remove_labels or [])
            m["label_ids"] = sorted(labels)
            _save(data)
            return {
                "ok": True,
                "source": self.name,
                "id": message_id,
                "label_ids": m["label_ids"],
            }
        return {
            "ok": False,
            "source": self.name,
            "error": "not_found",
            "message": f"找不到邮件: {message_id}",
        }


def _load() -> list[dict[str, Any]]:
    with MAIL_MOCK_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("messages") or [])


def _save(data: dict[str, Any]) -> None:
    MAIL_MOCK_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
