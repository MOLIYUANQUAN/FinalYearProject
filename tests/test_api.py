"""HTTP 接口：页面上是一条连着的对话，聊天走服务端会话，开场也记进对话，待确认的按钮刷新后还在。"""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.fake_model import call, text
from tests.helpers import SandboxTestCase

import src.main as main


def sse(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


class ApiTests(SandboxTestCase):
    def use(self, turns: list[list[tuple]]) -> None:
        self.service, _ = self.friday(turns)
        patcher = patch.object(main, "friday", self.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)

    def chat(self, message: str, cid: str | None = None) -> list[dict]:
        return sse(self.client.post("/api/chat/stream", json={"message": message, "conversation_id": cid}))

    def test_chat_then_reload_shows_the_same_conversation(self) -> None:
        self.use([[text("在。")]])
        events = self.chat("在吗")
        self.assertEqual(events[-1]["reply"], "在。")

        current = self.client.get("/api/conversation").json()
        self.assertEqual(current["id"], events[0]["id"])
        self.assertEqual([m["content"] for m in current["messages"]], ["在吗", "在。"])

    def test_one_thread_even_after_she_starts_a_fresh_session(self) -> None:
        self.use([[text("在。")], [text("记得，你刚问我在不在。")]])
        first = self.chat("在吗")[0]["id"]
        # 过了两小时：给模型的那段重开了，但页面上还是同一条，新的一段带着刚才那几句
        with patch("src.conversation.time.time", return_value=time.time() + 3 * 60 * 60):
            self.assertIsNone(self.client.get("/api/conversation").json()["id"])
            second = self.chat("我刚才问了什么")[0]["id"]
            thread = self.client.get("/api/conversation").json()["messages"]
        self.assertNotEqual(first, second)
        self.assertEqual([m["content"] for m in thread], ["在吗", "在。", "我刚才问了什么", "记得，你刚问我在不在。"])
        seen = str(self.service._model.inputs[-1])
        self.assertIn("在吗", seen)

    def test_opener_is_recorded_in_the_conversation(self) -> None:
        self.use([])
        events = sse(self.client.post("/api/presence/stream", json={}))
        self.assertEqual(events[0]["type"], "conversation")
        self.assertEqual(events[1]["type"], "agenda")
        opener = self.client.get("/api/conversation").json()["messages"][0]
        self.assertEqual(opener["agenda"]["hello"], events[1]["hello"])

    def test_opening_again_without_talking_does_not_stack_openers(self) -> None:
        self.use([])
        sse(self.client.post("/api/presence/stream", json={}))
        sse(self.client.post("/api/presence/stream", json={}))
        thread = self.client.get("/api/conversation").json()["messages"]
        self.assertEqual(len([m for m in thread if m.get("agenda")]), 1)

    def test_confirm_button_state_survives_reload(self) -> None:
        self.use([[call("send_email", to="a@b.c", subject="hi", body="hello", cc="")]])
        done = self.chat("发邮件")[-1]
        self.assertTrue(done["ask"].endswith("发吗？"))
        last = self.client.get("/api/conversation").json()["messages"][-1]
        self.assertTrue(last["needs_confirm"])
        self.assertIn("a@b.c", last["content"])
        self.assertEqual(last["ask"], done["ask"])

    def test_a_failure_reads_as_one_calm_line(self) -> None:
        self.use([])  # 脚本是空的：她一开口就出错
        error = self.chat("在吗")[-1]
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["message"], "这句没接上，再说一次。")

    def test_a_one_emoji_reply_is_a_reaction_on_his_message(self) -> None:
        self.use([[text("👍")]])
        done = self.chat("好的，下午搞定")[-1]
        self.assertEqual((done["reaction"], done["reply"]), ("👍", ""))
        thread = self.client.get("/api/conversation").json()["messages"]
        self.assertEqual([(m["role"], m.get("reaction")) for m in thread], [("user", "👍")])  # 没有多出一个她的气泡

    def test_he_reacts_on_her_bubble_and_she_sees_it_next_time(self) -> None:
        self.use([[text("明天下午 2 点见导师。\n\n在 Kilburn 1.10。")]])
        mid = self.chat("明天有什么")[-1]["message_id"]
        ok = self.client.post("/api/react", json={"message_id": mid, "part": 1, "emoji": "❤️"}).json()
        self.assertEqual(ok["reactions"], {"1": "❤️"})
        self.assertIn("「在 Kilburn 1.10。」❤️", self.service._context())
        self.assertEqual(self.client.post("/api/react", json={"message_id": mid, "part": 1, "emoji": "🤡"}).status_code, 400)
        removed = self.client.post("/api/react", json={"message_id": mid, "part": 1, "emoji": ""}).json()
        self.assertEqual(removed["reactions"], {})
        his = self.client.get("/api/conversation").json()["messages"][0]["id"]
        self.assertEqual(self.client.post("/api/react", json={"message_id": his, "emoji": "👍"}).status_code, 404)

    def test_revise_only_while_waiting_and_only_subject_or_body(self) -> None:
        self.use([[call("send_email", to="a@b.c", subject="hi", body="hello", cc="")], [call("send_email", to="a@b.c", subject="hi", body="hello!!", cc="")], [text("发了。")]])
        cid = self.chat("发邮件")[0]["id"]
        call_id = self.chat("发邮件", cid)[-1]["approvals"][0]["call_id"]
        bad = self.client.post("/api/chat/revise", json={"conversation_id": cid, "call_id": call_id, "changes": {"to": "evil@x.y"}})
        self.assertEqual(bad.status_code, 400)  # 收件人不能在卡片里偷偷换
        done = sse(self.client.post("/api/chat/revise", json={"conversation_id": cid, "call_id": call_id, "changes": {"body": "hello!!"}}))[-1]
        self.assertEqual(done["reply"], "发了。")
        again = self.client.post("/api/chat/revise", json={"conversation_id": cid, "call_id": call_id, "changes": {"body": "x"}})
        self.assertEqual(again.status_code, 409)


if __name__ == "__main__":
    unittest.main()
