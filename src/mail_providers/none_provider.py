"""邮件未启用。"""

from __future__ import annotations

from typing import Any


class DisabledMailProvider:
    name = "none"

    def search_messages(self, query: str, top: int = 5) -> dict[str, Any]:
        return {
            "ok": False,
            "source": self.name,
            "error": "mail_disabled",
            "message": (
                "邮件未启用。请在 .env 设置 MAIL_BACKEND=outlook 或 mock，"
                "并按 docs/outlook-mail-setup.md 完成配置。"
            ),
            "messages": [],
        }

    def get_message(self, message_id: str) -> dict[str, Any]:
        return self.search_messages("", 0)
