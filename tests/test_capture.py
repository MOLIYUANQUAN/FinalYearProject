"""随手交给 Friday：Siri / 快捷指令把一句话 POST 过来，她办完回一段能念的话；令牌只能进这一个口。"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.fake_model import call, text
from tests.helpers import SandboxTestCase

import src.capture as capture
import src.main as main


class CaptureTests(SandboxTestCase):
    def use(self, turns: list[list[tuple]]) -> None:
        friday, _ = self.friday(turns)
        self.service = friday
        for p in (patch.object(main, "friday", friday), patch.object(capture, "friday", friday)):
            p.start()
            self.addCleanup(p.stop)
        capture.TOKEN_PATH.unlink(missing_ok=True)
        self.client = TestClient(main.app)

    def test_siri_sentence_is_handled_and_spoken_back(self) -> None:
        self.use([[call("add_task", title="交 Lab 3", due="周五", notes="")], [text("记下了：**交 Lab 3**，周五截止。")]])
        token = self.client.get("/api/capture/setup").json()["token"]
        res = self.client.post("/api/capture", json={"text": "周五提醒我交 Lab 3"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, "记下了：交 Lab 3，周五截止。")  # 去掉了 Markdown，能直接念
        # 也出现在 Friday 的对话里
        cid = self.service.conversations.current()
        self.assertEqual(self.service.conversations.messages(cid)[0]["content"], "周五提醒我交 Lab 3")
        self.assertIsNotNone(self.client.get("/api/capture/setup").json()["used_at"])

    def test_plain_text_body_works_too(self) -> None:
        self.use([[text("在。")]])
        self.assertEqual(self.client.post("/api/capture", content="在吗".encode()).text, "在。")

    def test_writes_that_need_a_look_are_not_read_out(self) -> None:
        self.use([[call("send_email", to="a@b.c", subject="hi", body="一大段正文" * 20, cc="")]])
        res = self.client.post("/api/capture", json={"text": "给 a 发封邮件"})
        self.assertEqual(res.text, "邮件写好了，打开 Friday 看一眼，点确认就办。")
        self.assertEqual(self.sent_mail(), [])

    def test_empty_is_rejected(self) -> None:
        self.use([])
        self.assertEqual(self.client.post("/api/capture", json={"text": "  "}).status_code, 400)


class CaptureTokenTests(SandboxTestCase):
    """云上开了访问密码时：快捷指令令牌只能调 /api/capture，换一把旧的就失效。"""

    def setUp(self) -> None:
        super().setUp()
        friday, _ = self.friday([[text("好。")], [text("好。")]])
        for p in (
            patch.object(main, "friday", friday),
            patch.object(capture, "friday", friday),
            patch.dict(os.environ, {"FRIDAY_ACCESS_TOKEN": "pw"}),
        ):
            p.start()
            self.addCleanup(p.stop)
        capture.TOKEN_PATH.unlink(missing_ok=True)
        self.client = TestClient(main.app)
        self.token = self.client.get("/api/capture/setup", headers={"Authorization": "Bearer pw"}).json()["token"]

    def post(self, token: str, path: str = "/api/capture"):
        return self.client.post(path, json={"text": "在吗"}, headers={"Authorization": f"Bearer {token}"})

    def test_capture_token_only_opens_capture(self) -> None:
        self.assertEqual(self.client.post("/api/capture", json={"text": "在吗"}).status_code, 401)
        self.assertEqual(self.post(self.token).status_code, 200)
        self.assertEqual(self.client.get("/api/conversation", headers={"Authorization": f"Bearer {self.token}"}).status_code, 401)
        self.assertEqual(self.client.get("/api/capture/setup", headers={"Authorization": f"Bearer {self.token}"}).status_code, 401)

    def test_rotating_revokes_the_old_token(self) -> None:
        new = self.client.get("/api/capture/setup?rotate=true", headers={"Authorization": "Bearer pw"}).json()["token"]
        self.assertNotEqual(new, self.token)
        self.assertEqual(self.post(self.token).status_code, 401)
        self.assertEqual(self.post(new).status_code, 200)

    def test_setup_page_is_reachable_before_login(self) -> None:
        self.assertEqual(self.client.get("/siri").status_code, 200)


if __name__ == "__main__":
    unittest.main()
