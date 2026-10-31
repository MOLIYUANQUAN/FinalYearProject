"""改上一句（多半是没听准）：那一轮当没说过——她办掉的事撤回、等确认的那步作废、页面和给模型的那份都删掉，再按改过的这句重来。"""

from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.fake_model import call, text
from tests.helpers import SandboxTestCase

import src.main as main

WRONG = dict(title="见到时", start="2026-10-15T15:00", end="2026-10-15T16:00", location="", notes="")
RIGHT = dict(WRONG, title="见导师")
MAIL = {"to": "mentor.example@manchester.ac.uk", "subject": "FYP update", "body": "Hi.", "cc": ""}


def sse(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


class TakeBackTests(SandboxTestCase):
    def use(self, turns: list[list[tuple]]) -> TestClient:
        self.service, self.model = self.friday(turns)
        patcher = patch.object(main, "friday", self.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(main.app)

    def say(self, client: TestClient, message: str, *, replace: bool = False, cid: str | None = None) -> list[dict]:
        body = {"message": message, "conversation_id": cid, "replace_last": replace}
        return sse(client.post("/api/chat/stream", json=body))

    def test_the_misheard_line_is_taken_back_with_what_she_did(self) -> None:
        client = self.use([
            [call("create_calendar_event", **WRONG)], [text("加好了：见到时。")],
            [call("create_calendar_event", **RIGHT)], [text("加好了：见导师。")],
        ])
        cid = self.say(client, "明天三点见到时")[0]["id"]
        self.assertIn("见到时", self.calendar_titles())

        done = self.say(client, "明天三点见导师", replace=True, cid=cid)[-1]
        self.assertEqual(done["reply"], "加好了：见导师。")
        titles = self.calendar_titles()
        self.assertNotIn("见到时", titles)  # 听错那次加的撤回了
        self.assertIn("见导师", titles)
        thread = [m["content"] for m in client.get("/api/conversation").json()["messages"]]
        self.assertEqual(thread, ["明天三点见导师", "加好了：见导师。"])
        # 给模型的那份里也没有那句听错的和她那次的回答
        seen = str(self.model.inputs[2])
        self.assertNotIn("见到时", seen)
        self.assertIn("明天三点见导师", seen)

    def test_a_waiting_confirm_from_the_misheard_line_is_dropped(self) -> None:
        client = self.use([[call("send_email", **MAIL)], [text("好，那不发了，周二见。")]])
        first = self.say(client, "给导师发个进度")
        self.assertTrue(first[-1]["needs_confirm"])
        done = self.say(client, "跟导师说周二见", replace=True, cid=first[0]["id"])[-1]
        self.assertFalse(done["needs_confirm"])
        self.assertEqual(self.service.pending_approvals(first[0]["id"]), [])
        self.assertEqual(self.sent_mail(), [])
        self.assertNotIn("给导师发个进度", str(self.model.inputs[-1]))

    def test_a_line_that_never_reached_her_does_not_take_earlier_ones_with_it(self) -> None:
        client = self.use([[text("在。")], [text("在的，刚才那句没收到。")]])
        cid = self.say(client, "在吗")[0]["id"]
        self.service.conversations.add_message(cid, "user", "这句没进模型")  # 比如那一轮中途出错
        self.say(client, "刚才那句", replace=True, cid=cid)
        seen = str(self.model.inputs[-1])
        self.assertIn("在吗", seen)
        self.assertIn("在。", seen)
        thread = [m["content"] for m in client.get("/api/conversation").json()["messages"]]
        self.assertEqual(thread, ["在吗", "在。", "刚才那句", "在的，刚才那句没收到。"])

    def test_with_nothing_said_yet_it_is_just_a_message(self) -> None:
        client = self.use([[text("在。")]])
        done = self.say(client, "在吗", replace=True)[-1]
        self.assertEqual(done["reply"], "在。")

    def test_saying_it_again_replaces_the_misheard_line_too(self) -> None:
        from src import voice

        client = self.use([
            [call("create_calendar_event", **WRONG)], [text("加好了：见到时。")],
            [call("create_calendar_event", **RIGHT)], [text("加好了：见导师。")],
        ])
        cid = self.say(client, "明天三点见到时")[0]["id"]
        with patch.object(voice, "transcribe", return_value="明天三点见导师"):
            res = client.post("/api/voice/ask", data={"conversation_id": cid, "replace_last": "true"},
                              files={"file": ("speech.m4a", b"audio", "audio/mp4")})
        self.assertEqual(sse(res)[-1]["reply"], "加好了：见导师。")
        self.assertNotIn("见到时", self.calendar_titles())
        thread = [m["content"] for m in client.get("/api/conversation").json()["messages"]]
        self.assertEqual(thread, ["明天三点见导师", "加好了：见导师。"])
