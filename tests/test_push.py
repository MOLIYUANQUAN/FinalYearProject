"""Friday 主动来找他：加密对得上标准、什么时候说什么、每天不超过上限、同一件事只说一次。"""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi.testclient import TestClient

from src import nudges, push, webpush
from src.calendar_providers.mock import _load_raw_events
from src.main import app
from src.tasks_providers.mock import MockTasksProvider

EVENTS = _load_raw_events()  # 演示日历：10/13 10:00 讲座、14:00 见导师
TASKS = MockTasksProvider().list_open()  # 「准备 FYP meeting 的进度汇报」10/13 截止
SUB = {
    "endpoint": "https://web.push.apple.com/QH-test",
    "keys": {
        "p256dh": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
        "auth": "BTBZMqHH6r4Tts7J_aSIgg",
    },
}


def at(hhmm: str, day: str = "2026-10-13") -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}")


class WebPushCrypto(unittest.TestCase):
    def test_encryption_matches_rfc8291_example(self) -> None:
        sender = ec.derive_private_key(
            int.from_bytes(webpush.b64url_decode("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1()
        )
        body = webpush.encrypt(
            b"When I grow up, I want to be a watermelon",
            SUB["keys"]["p256dh"],
            SUB["keys"]["auth"],
            salt=webpush.b64url_decode("DGv6ra1nlYgDCS1FRnbzlw"),
            sender=sender,
        )
        self.assertEqual(
            webpush.b64url(body),
            "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8w"
            "EqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
        )

    def test_vapid_token_is_signed_for_the_push_service(self) -> None:
        header = webpush._vapid_header("https://web.push.apple.com/QH-test")
        token = header.split("t=")[1].split(",")[0]
        head, claims, sig = token.split(".")
        self.assertEqual(json.loads(webpush.b64url_decode(claims))["aud"], "https://web.push.apple.com")
        raw = webpush.b64url_decode(sig)
        signature = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        webpush.vapid_private_key().public_key().verify(signature, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
        self.assertTrue(header.endswith("k=" + webpush.vapid_public_key()))

    def test_send_posts_encrypted_body_and_drops_dead_subscriptions(self) -> None:
        with patch.object(webpush.requests, "post", return_value=MagicMock(status_code=201)) as post:
            webpush.send(SUB, {"title": "Friday", "body": "hi"})
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Content-Encoding"], "aes128gcm")
        self.assertTrue(headers["Authorization"].startswith("vapid t="))
        with patch.object(webpush.requests, "post", return_value=MagicMock(status_code=410)):
            with self.assertRaises(webpush.Gone):
                webpush.send(SUB, {"title": "x"})


class WhenToComeFindHim(unittest.TestCase):
    def test_morning_brief_lists_today_and_what_is_due(self) -> None:
        brief = next(n for n in nudges.candidates(at("08:40"), EVENTS, TASKS) if n["kind"] == "brief")
        body = brief["body"].replace(" ", " ")
        self.assertIn("今天 2 项", body)
        self.assertIn("上午 10 点", body)
        self.assertIn("下午 2 点", body)
        self.assertIn("今天截止：准备 FYP meeting 的进度汇报", body)

    def test_no_brief_before_morning_or_after_noon_or_on_an_empty_day(self) -> None:
        kinds = lambda now, tasks=TASKS: [n["kind"] for n in nudges.candidates(now, EVENTS, tasks)]  # noqa: E731
        self.assertNotIn("brief", kinds(at("07:59")))
        self.assertNotIn("brief", kinds(at("12:05")))
        self.assertNotIn("brief", kinds(at("09:00", "2026-10-16"), []))  # 没课没截止：不特意来说

    def test_important_meeting_two_hours_ahead_offers_to_prepare(self) -> None:
        meeting = next(n for n in nudges.candidates(at("12:30"), EVENTS, TASKS) if n["kind"] == "meeting")
        self.assertIn("FYP meeting with mentor", meeting["body"])
        self.assertIn("do=prepare", meeting["url"])
        self.assertEqual(meeting["urgency"], "high")

    def test_lectures_are_not_worth_a_push(self) -> None:
        self.assertEqual([n["kind"] for n in nudges.candidates(at("09:00"), EVENTS, []) if n["kind"] == "meeting"], [])

    def test_meeting_too_far_or_too_close_is_skipped(self) -> None:
        for hhmm in ("11:30", "13:50"):
            self.assertFalse([n for n in nudges.candidates(at(hhmm), EVENTS, TASKS) if n["kind"] == "meeting"], hhmm)

    def test_evening_reminder_for_what_is_still_due(self) -> None:
        due = next(n for n in nudges.candidates(at("17:30"), EVENTS, TASKS) if n["kind"] == "due")
        self.assertIn("今天截止还没划掉", due["body"])

    def test_quiet_hours(self) -> None:
        self.assertEqual(nudges.due_now(at("22:30"), EVENTS, TASKS), [])
        self.assertEqual(nudges.due_now(at("06:00"), EVENTS, TASKS), [])


class Delivery(unittest.TestCase):
    def setUp(self) -> None:
        for path in (nudges.SENT_PATH, push.SUBS_PATH):
            path.unlink(missing_ok=True)
        self.addCleanup(lambda: [p.unlink(missing_ok=True) for p in (nudges.SENT_PATH, push.SUBS_PATH)])
        self.sent: list[dict] = []

    def deliver(self, message, urgency="normal") -> int:
        self.sent.append(message)
        return 1

    def tick(self, now: datetime) -> list[dict]:
        with patch.object(nudges.agenda, "read", return_value=(EVENTS, now)), patch.object(
            nudges.todos, "read", return_value=(TASKS, now)
        ):
            return nudges.tick(now, deliver=self.deliver)

    def test_nothing_happens_without_a_device(self) -> None:
        self.assertEqual(self.tick(at("08:40")), [])
        self.assertEqual(self.sent, [])

    def test_each_thing_once_and_at_most_three_a_day(self) -> None:
        push.subscribe(SUB, "iPhone")
        self.assertEqual([n["kind"] for n in self.tick(at("08:40"))], ["brief"])
        self.assertEqual(self.tick(at("08:41")), [])  # 说过了
        self.assertEqual([n["kind"] for n in self.tick(at("12:30"))], ["meeting"])
        self.assertEqual([n["kind"] for n in self.tick(at("17:30"))], ["due"])
        self.assertEqual(self.tick(at("21:10")), [])  # 今天三条用完了：收工这条让给了更要紧的
        self.assertEqual(len(self.sent), 3)
        self.assertIn("do=prepare", self.sent[1]["url"])

    def test_dead_device_is_removed(self) -> None:
        push.subscribe(SUB, "iPhone")
        with patch.object(webpush, "send", side_effect=webpush.Gone("x")):
            self.assertEqual(push.deliver({"title": "x"}), 0)
        self.assertEqual(push.devices(), [])


class Api(unittest.TestCase):
    def setUp(self) -> None:
        push.SUBS_PATH.unlink(missing_ok=True)
        self.addCleanup(push.SUBS_PATH.unlink, missing_ok=True)
        self.client = TestClient(app)

    def test_subscribe_and_test_push(self) -> None:
        key = self.client.get("/api/push/key").json()
        self.assertEqual(len(webpush.b64url_decode(key["public_key"])), 65)
        self.assertEqual(self.client.post("/api/push/subscribe", json={"subscription": SUB, "device": "iPhone"}).json()["devices"], 1)
        self.assertEqual(self.client.post("/api/push/subscribe", json={"subscription": {"endpoint": "x"}}).status_code, 400)
        with patch.object(webpush.requests, "post", return_value=MagicMock(status_code=201)):
            self.assertEqual(self.client.post("/api/push/test").json()["delivered"], 1)

    def test_service_worker_is_served_at_the_root(self) -> None:
        res = self.client.get("/sw.js")
        self.assertEqual(res.status_code, 200)
        self.assertIn("showNotification", res.text)


if __name__ == "__main__":
    unittest.main()
