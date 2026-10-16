"""邮件数据源：none | mock | gmail | outlook。"""

from __future__ import annotations

from typing import Any, Protocol

from src.config import get_mail_backend


class MailProvider(Protocol):
    name: str

    def search_messages(self, query: str, top: int = 5) -> dict[str, Any]:
        ...

    def get_message(self, message_id: str) -> dict[str, Any]:
        ...


def get_mail_provider() -> MailProvider:
    backend = get_mail_backend()
    if backend == "gmail":
        from src.mail_providers.gmail import GmailMailProvider

        return GmailMailProvider()
    if backend == "outlook":
        from src.mail_providers.outlook import OutlookMailProvider

        return OutlookMailProvider()
    if backend == "mock":
        from src.mail_providers.mock import MockMailProvider

        return MockMailProvider()
    from src.mail_providers.none_provider import DisabledMailProvider

    return DisabledMailProvider()


__all__ = ["MailProvider", "get_mail_provider"]
