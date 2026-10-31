"""163 这类邮箱（地址 + 授权码，IMAP 收、SMTP 发）：对着本机的假 IMAP 服务器，imaplib 真的走一遍协议。

测：先报身份再开收件箱（163 的规矩）、中文标题和 GBK 的 HTML 信读得干净、按关键词和发件人找、正文里的词让服务器找、
读全文不标已读、附件名、发信走 SMTP 且留一份在「已发送」、标已读、删到「已删除」、没有归档就直说、授权码不对说怎么修、
放了地址和授权码就自动用这个邮箱，以及发信照旧要他确认。
"""

from __future__ import annotations

import base64
import imaplib
import os
import smtplib
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.fake_imap import SENT, TRASH, FakeImap, FakeSmtp
from tests.fake_model import call, text
from tests.helpers import SandboxTestCase

from src import config
from src.mail_providers import get_mail_provider
from src.mail_providers.imap import LOGIN_HELP, ImapMailProvider

WHEN = datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc)


def mentor() -> bytes:
    m = EmailMessage()
    m["From"] = "李老师 <li@manchester.ac.uk>"
    m["To"] = "zeep@163.com"
    m["Subject"] = "FYP 进度：下周二见面"
    m["Date"] = format_datetime(WHEN)
    m.set_content("Zeep 你好，\n\n下周二下午两点在 Kilburn 见，带上进度。\n\n李", cte="base64")
    return bytes(m)


def promo() -> bytes:
    """网易的通知：标的是 gb2312，用了 GBK 才有的字（镕）；只有 HTML。"""
    def word(s: str) -> str:
        return "=?gb2312?B?" + base64.b64encode(s.encode("gbk")).decode() + "?="
    html = "<html><body><p>您好，</p><p>朱镕的账单已出。</p><script>x()</script></body></html>"
    return (
        f"From: {word('网易邮箱')} <service@163.com>\r\n"
        f"To: zeep@163.com\r\n"
        f"Subject: {word('镕基金月度账单')}\r\n"
        f"Date: {format_datetime(WHEN + timedelta(days=1))}\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/html; charset=gb2312\r\n"
        "Content-Transfer-Encoding: base64\r\n\r\n"
        + base64.encodebytes(html.encode("gbk")).decode()
    ).encode()


def report() -> bytes:
    m = EmailMessage()
    m["From"] = "Amy <amy@student.manchester.ac.uk>"
    m["To"] = "zeep@163.com"
    m["Subject"] = "这周的东西"
    m["Date"] = format_datetime(WHEN + timedelta(days=2))
    m.set_content("附件是这周的报告，请查收。我们在实验室见。")
    m.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="报告.pdf")
    return bytes(m)


def mine() -> bytes:
    m = EmailMessage()
    m["From"] = "zeep@163.com"
    m["To"] = "li@manchester.ac.uk"
    m["Subject"] = "Re: FYP 进度"
    m["Date"] = format_datetime(WHEN + timedelta(hours=3))
    m.set_content("好的老师，周二见。")
    return bytes(m)


class MailboxCase(SandboxTestCase):
    uid_last = False
    special_use = False

    def setUp(self) -> None:
        super().setUp()
        self.fake = FakeImap(
            {"INBOX": [(mentor(), set()), (promo(), {"\\Seen"}), (report(), set())], SENT: [(mine(), {"\\Seen"})],
             TRASH: []},
            uid_last=self.uid_last, special_use=self.special_use,
        )
        self.addCleanup(self.fake.close)
        FakeSmtp.sent, FakeSmtp.logins = [], []
        self.hosts: list[str] = []

        def connect(host: str, port: int = 993, timeout: float | None = None) -> imaplib.IMAP4:
            self.hosts.append(host)
            return imaplib.IMAP4("127.0.0.1", self.fake.port, timeout=timeout)

        for patcher in (
            patch.dict(os.environ, {"MAIL_BACKEND": "imap", "MAIL_ADDRESS": "zeep@163.com", "MAIL_PASSWORD": "CODE"}),
            patch.object(imaplib, "IMAP4_SSL", connect),
            patch.object(smtplib, "SMTP_SSL", FakeSmtp),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.mail = ImapMailProvider()

    def inbox(self) -> list[dict]:
        return self.fake.boxes["INBOX"]


class ReadingTests(MailboxCase):
    def test_inbox_newest_first_with_clean_chinese_and_unread_marks(self) -> None:
        found = self.mail.search_messages("", 5)
        self.assertTrue(found["ok"], found)
        self.assertEqual(found["source"], "163 邮箱")
        self.assertEqual(self.hosts[0], "imap.163.com")
        got = [(m["subject"], m["unread"]) for m in found["messages"]]
        self.assertEqual(got, [("这周的东西", True), ("镕基金月度账单", False), ("FYP 进度：下周二见面", True)])
        promo_row = found["messages"][1]
        self.assertEqual(promo_row["from"], "网易邮箱 <service@163.com>")
        self.assertIn("朱镕的账单已出", promo_row["body_preview"])
        self.assertNotIn("x()", promo_row["body_preview"])
        self.assertEqual(found["messages"][2]["received"][:10], "2026-10-28")
        # 163 的规矩：登录后先报身份，再开收件箱
        self.assertLess(self.fake.commands.index("ID"), self.fake.commands.index("EXAMINE"))

    def test_words_match_subject_and_sender_and_gmail_style_filters_work(self) -> None:
        self.assertEqual([m["subject"] for m in self.mail.search_messages("导师 进度")["messages"]], [])
        self.assertEqual([m["subject"] for m in self.mail.search_messages("进度")["messages"]], ["FYP 进度：下周二见面"])
        self.assertEqual([m["subject"] for m in self.mail.search_messages("from:li")["messages"]], ["FYP 进度：下周二见面"])
        self.assertEqual([m["subject"] for m in self.mail.search_messages("is:unread", 5)["messages"]],
                         ["这周的东西", "FYP 进度：下周二见面"])
        sent = self.mail.search_messages("in:sent")["messages"]
        self.assertEqual([(m["subject"], m["id"].split(":")[0]) for m in sent], [("Re: FYP 进度", "sent")])

    def test_a_word_only_in_the_body_is_found_by_the_server(self) -> None:
        found = self.mail.search_messages("实验室")["messages"]
        self.assertEqual([m["subject"] for m in found], ["这周的东西"])
        self.assertEqual(self.fake.searched, ["实验室".encode("utf-8")])

    def test_reading_a_whole_mail_keeps_it_unread_and_lists_attachments(self) -> None:
        first = self.mail.search_messages("这周")["messages"][0]
        read = self.mail.get_message(first["id"])
        self.assertTrue(read["ok"], read)
        self.assertIn("我们在实验室见", read["message"]["body"])
        self.assertEqual(read["message"]["attachments"], ["报告.pdf"])
        self.assertTrue(read["message"]["unread"])
        self.assertNotIn("\\Seen", self.inbox()[2]["flags"])

    def test_a_made_up_id_is_not_found(self) -> None:
        self.assertFalse(self.mail.get_message("inbox:999")["ok"])
        self.assertFalse(self.mail.get_message("19a2b3")["ok"])


class UidAfterTheBody(ReadingTests):
    """有的服务器把 UID、FLAGS 放在内容后面：照样认。"""

    uid_last = True


class SpecialUseFolders(MailboxCase):
    special_use = True

    def test_folders_marked_sent_are_used(self) -> None:
        self.assertEqual([m["subject"] for m in self.mail.search_messages("in:sent")["messages"]], ["Re: FYP 进度"])


class WritingTests(MailboxCase):
    def test_sending_goes_out_by_smtp_and_a_copy_is_kept_in_sent(self) -> None:
        sent = self.mail.send_message(to="li@manchester.ac.uk", subject="周二见", body="老师好，周二两点见。")
        self.assertTrue(sent["ok"], sent)
        self.assertTrue(sent["kept_in_sent"])
        self.assertEqual(FakeSmtp.logins, [("zeep@163.com", "smtp.163.com")])
        out = FakeSmtp.sent[0]
        self.assertEqual((out["From"], out["To"], out["Subject"]), ("zeep@163.com", "li@manchester.ac.uk", "周二见"))
        self.assertTrue(out["Message-ID"])
        kept = self.fake.boxes[SENT][-1]
        self.assertIn("\\Seen", kept["flags"])
        self.assertIn(out["Message-ID"].encode(), kept["raw"])

    def test_mark_read_then_trash_moves_it_out_of_the_inbox(self) -> None:
        first = self.mail.search_messages("进度")["messages"][0]
        self.assertTrue(self.mail.modify_labels(message_id=first["id"], remove_labels=["UNREAD"])["ok"])
        self.assertIn("\\Seen", self.inbox()[0]["flags"])
        self.assertTrue(self.mail.modify_labels(message_id=first["id"], add_labels=["TRASH"], remove_labels=["INBOX"])["ok"])
        self.assertEqual(len(self.inbox()), 2)
        self.assertEqual(len(self.fake.boxes[TRASH]), 1)

    def test_archive_is_not_pretended(self) -> None:
        first = self.mail.search_messages("进度")["messages"][0]
        said = self.mail.modify_labels(message_id=first["id"], remove_labels=["INBOX"])
        self.assertEqual(said["error"], "archive_not_supported")
        self.assertEqual(len(self.inbox()), 3)


class WrongCodeTests(MailboxCase):
    def test_a_login_password_instead_of_the_code_says_how_to_fix_it(self) -> None:
        with patch.dict(os.environ, {"MAIL_PASSWORD": "my-login-password"}):
            mail = ImapMailProvider()
            found = mail.search_messages("")
        self.assertFalse(found["ok"])
        self.assertEqual(found["message"], LOGIN_HELP)
        with patch.dict(os.environ, {"MAIL_PASSWORD": "my-login-password"}), \
                patch.object(FakeSmtp, "password", "CODE"):
            self.assertEqual(ImapMailProvider().send_message(to="a@b.c", subject="x", body="y")["message"], LOGIN_HELP)

    def test_her_page_shows_the_fix_not_a_google_relogin(self) -> None:
        import src.main as main

        with patch.dict(os.environ, {"MAIL_PASSWORD": "my-login-password"}):
            rows = TestClient(main.app).get("/api/me").json()["connections"]
        row = next(r for r in rows if r["name"] == "邮件")
        self.assertFalse(row["ok"])
        self.assertIn("授权码", row["note"])


class ChoosingTheMailboxTests(SandboxTestCase):
    def test_an_address_and_code_switch_mail_to_that_mailbox(self) -> None:
        with patch.dict(os.environ, {"MAIL_BACKEND": "gmail", "MAIL_ADDRESS": "zeep@163.com", "MAIL_PASSWORD": "CODE"}):
            self.assertEqual(config.get_mail_backend(), "imap")
            self.assertIsInstance(get_mail_provider(), ImapMailProvider)
            from src.agent import _connections_line

            self.assertIn("163 邮箱", _connections_line())
        with patch.dict(os.environ, {"MAIL_BACKEND": "mock", "MAIL_ADDRESS": "zeep@163.com", "MAIL_PASSWORD": "CODE"}):
            self.assertEqual(config.get_mail_backend(), "mock")
        with patch.dict(os.environ, {"MAIL_BACKEND": "gmail", "MAIL_ADDRESS": "", "MAIL_PASSWORD": ""}):
            self.assertEqual(config.get_mail_backend(), "gmail")


class SendingStillAsksTests(MailboxCase):
    def test_she_asks_before_sending_from_163_and_sends_after_yes(self) -> None:
        import asyncio

        friday, _ = self.friday([
            [call("send_email", to="li@manchester.ac.uk", subject="周二见", body="老师好，周二两点见。")],
            [text("发了。")],
        ])

        async def scenario() -> tuple[dict, dict]:
            cid = friday.conversations.create()
            asked = [e async for e in friday.turn(cid, "跟李老师说周二两点见")][-1]
            self.assertEqual(FakeSmtp.sent, [])
            return asked, [e async for e in friday.turn(cid, "发")][-1]

        asked, done = asyncio.run(scenario())
        self.assertTrue(asked["needs_confirm"])
        self.assertEqual(done["reply"], "发了。")
        self.assertEqual(len(FakeSmtp.sent), 1)
        self.assertEqual(FakeSmtp.sent[0]["To"], "li@manchester.ac.uk")
