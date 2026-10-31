"""Gmail 和 163 一起看：一起搜、按时间排；读、删、回信各回各的邮箱；一个读不到不耽误另一个；发信卡片写从哪个发。

163 那边是本机的假 IMAP 服务器（imaplib 真的走协议），Gmail 用一个按脚本回话的替身。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.fake_imap import TRASH, FakeSmtp
from tests.fake_model import call, text
from tests.test_imap_mail import MailboxCase

from src import approval
from src.mail_providers import get_mail_provider
from src.mail_providers.several import Mailboxes

GMAIL = [
    {"id": "g1", "subject": "FYP poster deadline", "from": "School Office <office@manchester.ac.uk>",
     "received": "Thu, 29 Oct 2026 12:00:00 +0000", "body_preview": "Posters due Friday.", "label_ids": ["INBOX"]},
    {"id": "g0", "subject": "Your Google storage", "from": "Google <no-reply@google.com>",
     "received": "Mon, 26 Oct 2026 08:00:00 +0000", "body_preview": "15 GB", "label_ids": ["INBOX"]},
]


class FakeGmail:
    name = "gmail"
    sent: list[dict[str, Any]] = []
    trashed: list[str] = []
    broken = False

    def search_messages(self, query: str, top: int = 5) -> dict[str, Any]:
        if FakeGmail.broken:
            return {"ok": False, "source": "gmail", "error": "gmail_list_failed",
                    "message": "invalid_grant: Token has been expired or revoked."}
        words = [w.lower() for w in (query or "").split() if ":" not in w]
        found = [m for m in GMAIL if all(w in (m["subject"] + m["from"]).lower() for w in words)]
        return {"ok": True, "source": "gmail", "query": query, "messages": found[:top]}

    def get_message(self, message_id: str) -> dict[str, Any]:
        m = next((m for m in GMAIL if m["id"] == message_id), None)
        return {"ok": True, "source": "gmail", "message": {**m, "body": "Posters due Friday 5pm."}} if m else \
            {"ok": False, "source": "gmail", "error": "gmail_get_failed", "message": "not found"}

    def send_message(self, *, to: str, subject: str, body: str, cc: str = "") -> dict[str, Any]:
        FakeGmail.sent.append({"to": to, "subject": subject, "body": body})
        return {"ok": True, "source": "gmail", "id": "g-sent", "to": to, "subject": subject}

    def modify_labels(self, *, message_id: str, add_labels: list[str] | None = None,
                      remove_labels: list[str] | None = None) -> dict[str, Any]:
        FakeGmail.trashed.append(message_id)
        return {"ok": True, "source": "gmail", "id": message_id}


class BothMailboxesCase(MailboxCase):
    def setUp(self) -> None:
        super().setUp()
        FakeGmail.sent, FakeGmail.trashed, FakeGmail.broken = [], [], False
        for patcher in (
            patch.dict(os.environ, {"MAIL_BACKEND": "gmail"}),
            patch("src.mail_providers.gmail.GmailMailProvider", FakeGmail),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.both = get_mail_provider()


class ReadingBothTests(BothMailboxesCase):
    def test_one_search_covers_both_newest_first(self) -> None:
        self.assertIsInstance(self.both, Mailboxes)
        found = self.both.search_messages("", 4)
        self.assertTrue(found["ok"], found)
        got = [(m["mailbox"], m["subject"]) for m in found["messages"]]
        self.assertEqual(got, [("163 邮箱", "这周的东西"), ("Gmail", "FYP poster deadline"),
                               ("163 邮箱", "镕基金月度账单"), ("163 邮箱", "FYP 进度：下周二见面")])
        self.assertTrue(found["messages"][1]["id"].startswith("gmail:"))
        self.assertTrue(found["messages"][0]["id"].startswith("163:inbox:"))
        self.assertEqual(found["messages"][1]["received"][:10], "2026-10-29")  # Gmail 的日期也换成一样的写法

    def test_a_word_is_looked_for_in_both(self) -> None:
        found = self.both.search_messages("FYP")["messages"]
        self.assertEqual([(m["mailbox"], m["subject"]) for m in found],
                         [("Gmail", "FYP poster deadline"), ("163 邮箱", "FYP 进度：下周二见面")])

    def test_reading_goes_to_the_mailbox_it_came_from(self) -> None:
        found = {m["mailbox"]: m["id"] for m in self.both.search_messages("FYP")["messages"]}
        from_163 = self.both.get_message(found["163 邮箱"])
        from_gmail = self.both.get_message(found["Gmail"])
        self.assertIn("Kilburn", from_163["message"]["body"])
        self.assertEqual(from_163["message"]["mailbox"], "163 邮箱")
        self.assertEqual(from_gmail["message"]["body"], "Posters due Friday 5pm.")
        self.assertFalse(self.both.get_message("nowhere:1")["ok"])

    def test_deleting_goes_to_the_mailbox_it_came_from(self) -> None:
        found = {m["mailbox"]: m["id"] for m in self.both.search_messages("FYP")["messages"]}
        self.assertTrue(self.both.modify_labels(message_id=found["163 邮箱"], add_labels=["TRASH"])["ok"])
        self.assertEqual(len(self.fake.boxes[TRASH]), 1)
        self.both.modify_labels(message_id=found["Gmail"], add_labels=["TRASH"])
        self.assertEqual(FakeGmail.trashed, ["g1"])


class OneMailboxDownTests(BothMailboxesCase):
    def test_gmail_down_still_shows_163_and_says_gmail_was_not_read(self) -> None:
        FakeGmail.broken = True
        found = self.both.search_messages("FYP")
        self.assertTrue(found["ok"])
        self.assertEqual([m["mailbox"] for m in found["messages"]], ["163 邮箱"])
        self.assertEqual(found["problems"][0]["mailbox"], "Gmail")

    def test_both_down_is_an_error_naming_both(self) -> None:
        FakeGmail.broken = True
        with patch.dict(os.environ, {"MAIL_PASSWORD": "wrong"}):
            found = get_mail_provider().search_messages("")
        self.assertFalse(found["ok"])
        self.assertIn("Gmail：", found["message"])
        self.assertIn("163 邮箱：", found["message"])

    def test_her_page_has_a_row_for_each_mailbox(self) -> None:
        import src.main as main

        FakeGmail.broken = True
        rows = {r["name"]: r for r in TestClient(main.app).get("/api/me").json()["connections"]}
        self.assertTrue(rows["163 邮箱"]["ok"])
        self.assertFalse(rows["Gmail"]["ok"])
        self.assertIn("重新登录 Google", rows["Gmail"]["note"])


class SendingFromTheRightMailboxTests(BothMailboxesCase):
    def test_new_mail_goes_from_163_and_the_card_says_so(self) -> None:
        card = approval.describe("send_email", {"to": "li@manchester.ac.uk", "subject": "周二见", "body": "老师好"})
        self.assertIn("从 163 邮箱 发", card)
        sent = self.both.send_message(to="li@manchester.ac.uk", subject="周二见", body="老师好")
        self.assertEqual(sent["mailbox"], "163 邮箱")
        self.assertEqual(len(FakeSmtp.sent), 1)
        self.assertEqual(FakeGmail.sent, [])

    def test_a_reply_to_a_gmail_mail_goes_from_gmail(self) -> None:
        card = approval.describe("send_email", {"to": "office@manchester.ac.uk", "subject": "Re: poster", "body": "OK",
                                                "mailbox": "Gmail"})
        self.assertIn("从 Gmail 发", card)
        self.both.send_message(to="office@manchester.ac.uk", subject="Re: poster", body="OK", mailbox="Gmail")
        self.assertEqual(len(FakeGmail.sent), 1)
        self.assertEqual(FakeSmtp.sent, [])

    def test_she_asks_with_the_mailbox_on_the_card_then_sends_from_it(self) -> None:
        friday, _ = self.friday([
            [call("send_email", to="office@manchester.ac.uk", subject="Re: poster", body="Will do.", mailbox="Gmail")],
            [text("发了。")],
        ])

        async def scenario() -> tuple[dict, dict]:
            cid = friday.conversations.create()
            asked = [e async for e in friday.turn(cid, "回一下学校那封海报的信，说好的")][-1]
            return asked, [e async for e in friday.turn(cid, "发")][-1]

        asked, done = asyncio.run(scenario())
        self.assertTrue(asked["needs_confirm"])
        self.assertIn("从 Gmail 发", asked["ask"])
        self.assertEqual(done["reply"], "发了。")
        self.assertEqual([m["to"] for m in FakeGmail.sent], ["office@manchester.ac.uk"])
        self.assertEqual(FakeSmtp.sent, [])

    def test_with_one_mailbox_the_card_does_not_mention_it(self) -> None:
        with patch.dict(os.environ, {"MAIL_BACKEND": "none"}):
            card = approval.describe("send_email", {"to": "a@b.c", "subject": "x", "body": "y"})
        self.assertNotIn("从 ", card)
