"""邮件数据源。

MAIL_BACKEND 是 Gmail / Outlook / 演示邮箱那一个；放了地址和授权码的邮箱（163、QQ……）不管它是什么都一起看。
接了不止一个就合在一起（several.Mailboxes）：一起搜、按时间排；读、改、回信各回各的邮箱。
"""

from __future__ import annotations

from typing import Any, Protocol

from src.config import get_mail_backend


class MailProvider(Protocol):
    name: str

    def search_messages(self, query: str, top: int = 5) -> dict[str, Any]:
        ...

    def get_message(self, message_id: str) -> dict[str, Any]:
        ...


LABELS = {"gmail": "Gmail", "outlook": "Outlook", "mock": "演示邮箱"}


def label_of(box: Any) -> str:
    return getattr(box, "label", None) or LABELS.get(getattr(box, "name", ""), "邮箱")


def mailboxes() -> list[Any]:
    """他接上的每个邮箱，主的（Gmail）在前。"""
    backend = get_mail_backend()
    if backend == "mock":
        from src.mail_providers.mock import MockMailProvider

        return [MockMailProvider()]
    boxes: list[Any] = []
    if backend == "gmail":
        from src.mail_providers.gmail import GmailMailProvider

        boxes.append(GmailMailProvider())
    elif backend == "outlook":
        from src.mail_providers.outlook import OutlookMailProvider

        boxes.append(OutlookMailProvider())
    from src.mail_providers.imap import ImapMailProvider, accounts

    boxes += [ImapMailProvider(address, password) for address, password in accounts()]
    return boxes


def get_mail_provider() -> Any:
    boxes = mailboxes()
    if len(boxes) > 1:
        from src.mail_providers.several import Mailboxes

        return Mailboxes(boxes)
    if boxes:
        return boxes[0]
    from src.mail_providers.none_provider import DisabledMailProvider

    return DisabledMailProvider()


def sender_label(mailbox: str = "") -> str:
    """接了不止一个邮箱时，这封信会从哪个发（确认卡片上写给他看）；只有一个就不用说。"""
    provider = get_mail_provider()
    pick = getattr(provider, "sender", None)
    return label_of(pick(mailbox)[1]) if pick else ""


__all__ = ["MailProvider", "get_mail_provider", "label_of", "mailboxes", "sender_label"]
