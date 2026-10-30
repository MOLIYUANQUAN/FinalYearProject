"""开工台：卡片每行能点；「需要你」只放要他拍板的；点一下就办，记进对话，能撤销。"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import SandboxTestCase

import src.workbench as workbench
from src import presence, todos
from src.calendar_providers.mock import _load_raw_events
from src.tasks_providers.mock import MockTasksProvider

EVENTS = _load_raw_events()


def at(hhmm: str, day: str = "2026-10-13") -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}")


def view(now: datetime, tasks: list[dict]):
    found, say, focus = presence.today_view(now, EVENTS, tasks)
    return {s["label"]: s for s in found}, say.replace("\u00a0", " "), focus


class NowTests(unittest.TestCase):
    """打开就是「现在」：一句话、一个动作；下面一条时间线，没有分区标题。"""

    TASKS = [
        {"id": "t-old", "title": "交 Lab 2", "due": "2026-10-11"},
        {"id": "t-today", "title": "准备进度汇报", "due": "2026-10-13"},
        {"id": "t-tomorrow", "title": "续借图书馆的书", "due": "2026-10-14"},
    ]
    def test_important_meeting_soon_comes_first(self) -> None:
        _, say, focus = view(at("12:00"), self.TASKS)
        # 第一句只说最要紧的（大字），地点和还剩多久在后面（小字）
        self.assertEqual(say, "下午 2 点 FYP meeting with mentor。Kilburn Building · 还有 2 小时。")
        self.assertEqual([a["id"] for a in focus["actions"]], ["prepare"])

    def test_then_overdue_then_due_today(self) -> None:
        _, say, focus = view(at("09:00"), self.TASKS)
        self.assertEqual((say, focus["key"]), ("过了截止还没划掉：交 Lab 2。", "task:t-old"))
        _, say, focus = view(at("09:00"), self.TASKS[1:])
        self.assertEqual(say, "今天截止：准备进度汇报。")
        self.assertEqual([a["id"] for a in focus["actions"]], ["done", "tomorrow"])

    def test_nothing_pressing_falls_back_to_the_calendar_line(self) -> None:
        _, say, focus = view(at("09:00", "2026-10-12"), [])
        self.assertIsNone(focus)
        self.assertIn("明天下午 2 点", say)

    def test_one_timeline_per_day_with_reminders_and_deadlines(self) -> None:
        from src import reminders

        reminders.REMINDERS_PATH.unlink(missing_ok=True)
        self.addCleanup(reminders.REMINDERS_PATH.unlink, missing_ok=True)
        reminders.add("给妈妈打电话", at("15:30"))
        card, _, _ = view(at("09:00"), self.TASKS)
        self.assertEqual(list(card), ["今天", "明天 · 周三"])  # 没有「需要你」「待办」这些分区
        empty, _, _ = view(at("09:00", "2026-10-16"), [])  # 周五：今天明天都空
        self.assertEqual(list(empty), [])  # 空的日子不占地方
        today = [(r["time"], r["title"]) for r in card["今天"]["rows"]]
        self.assertEqual(today, [
            ("10:00–11:00", "Comp30291 lecture"),
            ("14:00–15:00", "FYP meeting with mentor"),
            ("15:30", "提醒：给妈妈打电话"),
            ("过了 2 天", "交 Lab 2"),
            ("截止", "准备进度汇报"),
        ])
        self.assertEqual(card["明天 · 周三"]["rows"][-1]["title"], "续借图书馆的书")

    def test_something_left_for_days_is_not_now(self) -> None:
        """10/18 的旧待办放了 12 天：不顶到最上面，也不推送；时间线上问一句「做完了 / 不要了」。"""
        stale = [{"id": "t-stale", "title": "明天中午十二点开会", "due": "2026-10-01"}]
        card, say, focus = view(at("09:00"), stale)
        self.assertIsNone(focus)
        self.assertNotIn("明天中午十二点开会", say)
        row = card["今天"]["rows"][-1]
        self.assertEqual((row["time"], [a["id"] for a in row["actions"]]), ("放了 12 天", ["done", "drop"]))

        from src import nudges

        self.assertEqual(nudges._due_today(at("17:30"), stale), ([], []))

    def test_rows_still_carry_their_actions(self) -> None:
        card, _, _ = view(at("09:00", "2026-10-12"), self.TASKS[1:])
        rows = {r["title"]: r for r in card["明天 · 周二"]["rows"]}
        self.assertEqual([a["id"] for a in rows["FYP meeting with mentor"]["actions"]], ["prepare"])
        self.assertEqual(rows["Comp30291 lecture"]["actions"], [])  # 讲座不用准备
        self.assertEqual(rows["准备进度汇报"]["key"], "task:t-today")


class ActTests(SandboxTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provider = MockTasksProvider()
        self.tasks = [{"id": "t1", "title": "交 Lab 2", "due": "2026-10-11"}]
        friday, _ = self.friday([])
        patches = [
            patch.object(workbench, "friday", friday),
            patch.object(workbench, "get_tasks_provider", return_value=self.provider),
            patch.object(todos, "read", side_effect=lambda *a, **k: (self.tasks, at("09:00"))),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.friday_service = friday
        app = FastAPI()
        app.include_router(workbench.router)
        self.client = TestClient(app)

    def test_done_completes_records_and_offers_undo(self) -> None:
        with patch.object(self.provider, "complete", return_value=self.tasks[0]) as complete:
            data = self.client.post("/api/items/act", json={"key": "task:t1", "action": "done"}).json()
        complete.assert_called_once_with("t1")
        self.assertEqual(data["say"], "划掉了：交 Lab 2。")
        self.assertEqual(data["undo"][0]["kind"], "task_completed")
        last = self.friday_service.conversations.messages(data["conversation_id"])[-1]
        self.assertEqual(last["content"], "划掉了：交 Lab 2。")

    def test_tomorrow_moves_the_due_date_and_undo_restores_it(self) -> None:
        with patch.object(self.provider, "set_due", return_value=self.tasks[0]) as set_due:
            data = self.client.post("/api/items/act", json={"key": "task:t1", "action": "tomorrow"}).json()
        self.assertEqual(set_due.call_args.args[0], "t1")
        self.assertEqual(data["undo"][0]["due"], "2026-10-11")

    def test_drop_takes_it_off_without_counting_it_as_closed(self) -> None:
        from src import closed

        closed.CLOSED_PATH.unlink(missing_ok=True)
        self.addCleanup(closed.CLOSED_PATH.unlink, missing_ok=True)
        with patch.object(self.provider, "complete", return_value=self.tasks[0]) as complete:
            data = self.client.post("/api/items/act", json={"key": "task:t1", "action": "drop"}).json()
        complete.assert_called_once_with("t1")
        self.assertEqual(data["say"], "好，不再提：交 Lab 2。")
        self.assertEqual(closed.on_day(closed.effective_now().date()), [])

    def test_unknown_or_gone_rows(self) -> None:
        self.assertEqual(self.client.post("/api/items/act", json={"key": "task:nope", "action": "done"}).status_code, 404)
        self.assertEqual(self.client.post("/api/items/act", json={"key": "event:x", "action": "done"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
