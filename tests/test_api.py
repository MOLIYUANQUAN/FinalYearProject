"""HTTP 接口：页面打开接上当前对话、聊天走服务端会话、「说错了」记得下来。"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.fake_model import call, text
from tests.helpers import SandboxTestCase

import src.main as main
from src import mistakes


def sse(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


class ApiTests(SandboxTestCase):
    def use(self, turns: list[list[tuple]]) -> None:
        friday, _ = self.friday(turns)
        patcher = patch.object(main, "friday", friday)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)

    def test_chat_then_reload_shows_the_same_conversation(self) -> None:
        self.use([[text("在。")]])
        cid = self.client.post("/api/conversation/new").json()["id"]
        events = sse(self.client.post("/api/chat/stream", json={"message": "在吗", "conversation_id": cid}))
        self.assertEqual(events[-1]["reply"], "在。")

        current = self.client.get("/api/conversation").json()
        self.assertEqual(current["id"], cid)
        self.assertEqual([m["content"] for m in current["messages"]], ["在吗", "在。"])

    def test_opener_is_recorded_in_the_conversation(self) -> None:
        self.use([])
        cid = self.client.post("/api/conversation/new").json()["id"]
        events = sse(self.client.post("/api/presence/stream", json={"conversation_id": cid}))
        self.assertEqual(events[0]["type"], "agenda")
        opener = self.client.get("/api/conversation").json()["messages"][0]
        self.assertEqual(opener["agenda"]["hello"], events[0]["hello"])

    def test_confirm_button_state_survives_reload(self) -> None:
        self.use([[call("send_email", to="a@b.c", subject="hi", body="hello", cc="")]])
        cid = self.client.post("/api/conversation/new").json()["id"]
        sse(self.client.post("/api/chat/stream", json={"message": "发邮件", "conversation_id": cid}))
        last = self.client.get("/api/conversation").json()["messages"][-1]
        self.assertTrue(last["needs_confirm"])
        self.assertIn("a@b.c", last["content"])

    def test_wrong_button_records_question_and_answer(self) -> None:
        self.use([[text("明天有实验课。")]])
        mistakes.MISTAKES_PATH.unlink(missing_ok=True)
        cid = self.client.post("/api/conversation/new").json()["id"]
        done = sse(self.client.post("/api/chat/stream", json={"message": "明天有什么课", "conversation_id": cid}))[-1]

        self.assertTrue(self.client.post("/api/wrong", json={"message_id": done["message_id"]}).json()["ok"])
        item = mistakes.all_items()[-1]
        self.assertEqual((item["asked"], item["said"]), ("明天有什么课", "明天有实验课。"))
        self.assertTrue(self.client.get("/api/conversation").json()["messages"][-1]["wrong"])
        self.assertEqual(self.client.post("/api/wrong", json={"message_id": 999999}).status_code, 404)


    def test_revise_only_while_waiting_and_only_subject_or_body(self) -> None:
        self.use([[call("send_email", to="a@b.c", subject="hi", body="hello", cc="")], [call("send_email", to="a@b.c", subject="hi", body="hello!!", cc="")], [text("发了。")]])
        cid = self.client.post("/api/conversation/new").json()["id"]
        call_id = sse(self.client.post("/api/chat/stream", json={"message": "发邮件", "conversation_id": cid}))[-1]["approvals"][0]["call_id"]
        bad = self.client.post("/api/chat/revise", json={"conversation_id": cid, "call_id": call_id, "changes": {"to": "evil@x.y"}})
        self.assertEqual(bad.status_code, 400)  # 收件人不能在卡片里偷偷换
        done = sse(self.client.post("/api/chat/revise", json={"conversation_id": cid, "call_id": call_id, "changes": {"body": "hello!!"}}))[-1]
        self.assertEqual(done["reply"], "发了。")
        again = self.client.post("/api/chat/revise", json={"conversation_id": cid, "call_id": call_id, "changes": {"body": "x"}})
        self.assertEqual(again.status_code, 409)


if __name__ == "__main__":
    unittest.main()
