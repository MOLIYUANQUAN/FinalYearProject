"""准时提醒：他的原话由服务端换成时刻；到点一定叫他（不占名额、夜里也叫）；能撤销；截止日前一晚自己提一句。"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.fake_model import call, text
from tests.helpers import SandboxTestCase, collect

import src.main as main
from src import nudges, push, reminders
from src.reminders import parse_when

FRIDAY_4PM = datetime(2026, 10, 30, 16, 0)  # 周五下午 4 点
SUB = {"endpoint": "https://push.example/x", "keys": {"p256dh": "k", "auth": "a"}}


class ParseWhen(unittest.TestCase):
    CASES = {
        "20分钟后": "2026-10-30 16:20",
        "半小时后": "2026-10-30 16:30",
        "一个半小时后": "2026-10-30 17:30",
        "8点": "2026-10-30 20:00",  # 今天还没过的那个 8 点
        "3点": "2026-10-31 15:00",  # 今天的 3 点都过了：明天下午
        "下午三点": "2026-10-31 15:00",
        "今晚8点": "2026-10-30 20:00",
        "八点一刻": "2026-10-30 20:15",
        "十点零五": "2026-10-30 22:05",
        "明早8点": "2026-10-31 08:00",
        "明天3点": "2026-10-31 15:00",  # 明天说 3 点多半是下午
        "明天早上7点半": "2026-10-31 07:30",
        "明天": "2026-10-31 09:00",
        "中午1点": "2026-10-31 13:00",
        "凌晨1点": "2026-10-31 01:00",
        "周五晚上8点": "2026-10-30 20:00",
        "下周一上午10点": "2026-11-02 10:00",
        "后天下午": "2026-11-01 15:00",
        "2026-11-02 09:30": "2026-11-02 09:30",
    }

    def test_his_words_become_a_time(self) -> None:
        for said, expected in self.CASES.items():
            at = parse_when(said, FRIDAY_4PM)
            self.assertEqual(at and at.strftime("%Y-%m-%d %H:%M"), expected, said)

    def test_vague_or_past_is_not_guessed(self) -> None:
        for said in ("等会儿", "改天", "今天"):  # 今天早上 9 点已经过了
            self.assertIsNone(parse_when(said, FRIDAY_4PM), said)

    def test_said_back_in_plain_words(self) -> None:
        said = lambda w: reminders.said_when(parse_when(w, FRIDAY_4PM), FRIDAY_4PM).replace(" ", " ")  # noqa: E731
        self.assertEqual(said("20分钟后"), "20 分钟后（下午4:20）")
        self.assertEqual(said("明早8点"), "明天上午8点")
        self.assertEqual(said("下周一上午10点"), "周一上午10点")


class Flow(SandboxTestCase):
    def setUp(self) -> None:
        super().setUp()
        for path in (reminders.REMINDERS_PATH, nudges.SENT_PATH, push.SUBS_PATH):
            path.unlink(missing_ok=True)
            self.addCleanup(path.unlink, missing_ok=True)

    def test_she_sets_it_from_his_words_and_it_can_be_undone(self) -> None:
        push.subscribe(SUB, "iPhone")
        friday, _ = self.friday([[call("remind_me", what="给妈妈打电话", when="20分钟后")], [text("ignored")]])
        cid = friday.conversations.create()
        with patch("src.tools.reminders.effective_now", return_value=FRIDAY_4PM):
            done = collect(friday.turn(cid, "20分钟后提醒我给妈妈打电话"))[-1]
        self.assertEqual(reminders.pending()[0]["at"], "2026-10-30T16:20")
        self.assertEqual(done["undo"][0]["kind"], "reminder_added")

        with patch.object(main, "friday", friday):
            TestClient(main.app).post("/api/undo", json={"items": done["undo"]})
        self.assertEqual(reminders.pending(), [])

    def test_unclear_time_makes_her_ask(self) -> None:
        friday, model = self.friday([[call("remind_me", what="开会", when="等会儿")], [text("几点？")]])
        cid = friday.conversations.create()
        done = collect(friday.turn(cid, "等会儿提醒我开会"))[-1]
        self.assertEqual(done["reply"], "几点？")
        self.assertIn("when_unclear", str(model.inputs[-1]))
        self.assertEqual(reminders.pending(), [])

    def test_she_warns_when_no_device_can_be_reached(self) -> None:
        friday, model = self.friday([[call("remind_me", what="交报告", when="明早8点")], [text("x")]])
        cid = friday.conversations.create()
        collect(friday.turn(cid, "明早8点提醒我交报告"))
        self.assertIn("打开提醒", str(model.inputs[-1]))  # 工具结果里就写明了：到点没法找你

    def tick(self, now: datetime, tasks=None) -> list[dict]:
        self.sent: list[dict] = []

        def deliver(message, urgency="normal"):
            self.sent.append({**message, "urgency": urgency})
            return 1

        with patch.object(nudges.agenda, "read", return_value=([], now)), patch.object(
            nudges.todos, "read", return_value=(tasks or [], now)
        ), patch.object(nudges.engineering, "events", return_value=[]):
            return nudges.tick(now, deliver=deliver)

    def test_fires_on_the_minute_even_at_night_and_past_the_quota(self) -> None:
        push.subscribe(SUB, "iPhone")
        reminders.add("吃药", datetime(2026, 10, 30, 23, 30))
        self.assertEqual(self.tick(datetime(2026, 10, 30, 23, 29)), [])
        sent = self.tick(datetime(2026, 10, 30, 23, 30))
        self.assertEqual([n["kind"] for n in sent], ["reminder"])
        self.assertEqual((self.sent[0]["body"], self.sent[0]["urgency"]), ("吃药。", "high"))
        self.assertEqual(self.tick(datetime(2026, 10, 30, 23, 31)), [])  # 只叫一次

    def test_long_missed_reminders_are_dropped_not_sent_late(self) -> None:
        push.subscribe(SUB, "iPhone")
        reminders.add("早上的会", datetime(2026, 10, 30, 8, 0))
        self.assertEqual(self.tick(datetime(2026, 10, 30, 16, 0)), [])
        self.assertEqual(reminders.pending(), [])

    def test_the_evening_before_a_deadline(self) -> None:
        push.subscribe(SUB, "iPhone")
        tasks = [{"id": "t", "title": "交 Lab 3", "due": "2026-10-31"}]
        sent = self.tick(datetime(2026, 10, 30, 20, 5), tasks)
        self.assertEqual([n["kind"] for n in sent], ["eve"])
        self.assertIn("明天截止：交 Lab 3", self.sent[0]["body"].replace(" ", " "))


if __name__ == "__main__":
    unittest.main()
