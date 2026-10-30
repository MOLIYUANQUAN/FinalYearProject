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


def sections(now: datetime, tasks: list[dict]) -> dict[str, dict]:
    found, _say = presence.today_view(now, EVENTS, tasks)
    return {s["label"]: s for s in found}


class CardTests(unittest.TestCase):
    TASKS = [
        {"id": "t-old", "title": "交 Lab 2", "due": "2026-10-11"},
        {"id": "t-today", "title": "准备进度汇报", "due": "2026-10-13"},
        {"id": "t-tomorrow", "title": "续借图书馆的书", "due": "2026-10-14"},
    ]

    def test_needs_you_only_holds_decisions(self) -> None:
        card = sections(at("12:00"), self.TASKS)
        needs = card["需要你"]
        self.assertEqual(list(card)[0], "需要你")  # 放在最上面
        titles = [r["title"] for r in needs["rows"]]
        self.assertEqual(titles, ["FYP meeting with mentor", "交 Lab 2"])  # 三小时内的要紧会 + 过了截止的
        self.assertNotIn("准备进度汇报", titles)  # 今天截止的还不用拍板
        self.assertEqual([a["id"] for a in needs["rows"][1]["actions"]], ["done", "tomorrow"])

    def test_no_needs_you_when_nothing_needs_him(self) -> None:
        card = sections(at("09:00", "2026-10-12"), [{"id": "t", "title": "x", "due": "2026-10-13"}])
        self.assertNotIn("需要你", card)  # 明天的会、明天截止的都不进来

    def test_rows_carry_actions(self) -> None:
        card = sections(at("09:00", "2026-10-12"), self.TASKS[1:])
        meeting = next(r for r in card["明天 · 周二"]["rows"] if r["title"] == "FYP meeting with mentor")
        lecture = next(r for r in card["明天 · 周二"]["rows"] if r["title"] == "Comp30291 lecture")
        self.assertEqual([a["id"] for a in meeting["actions"]], ["prepare"])
        self.assertEqual(lecture["actions"], [])  # 讲座不用准备
        self.assertEqual(card["待办"]["rows"][0]["key"], "task:t-today")


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

    def test_unknown_or_gone_rows(self) -> None:
        self.assertEqual(self.client.post("/api/items/act", json={"key": "task:nope", "action": "done"}).status_code, 404)
        self.assertEqual(self.client.post("/api/items/act", json={"key": "event:x", "action": "done"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
