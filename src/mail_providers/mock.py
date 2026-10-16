"""本地 JSON mock 邮件。"""

from __future__ import annotations

import json
from typing import Any

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
        items = sorted(items, key=lambda m: m.get("received") or "", reverse=True)[: max(1, min(top, 20))]
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


def _load() -> list[dict[str, Any]]:
    with MAIL_MOCK_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("messages") or [])
