"""他发截图和照片：只收图片、存在云上；对话里只记编号，问模型时才把图读出来；Claude 那边图在前、字在后。"""

from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.fake_model import text
from tests.helpers import SandboxTestCase, collect

import src.main as main
from src import claude, uploads

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class UploadTests(SandboxTestCase):
    def test_only_pictures_are_kept(self) -> None:
        saved = uploads.save(PNG)
        self.assertEqual(saved["url"], uploads.PREFIX + saved["id"])
        self.assertTrue(uploads.data_url(saved["url"]).startswith("data:image/png;base64,"))
        with self.assertRaises(ValueError):
            uploads.save(b"%PDF-1.7 not a picture")
        self.assertIsNone(uploads.find("../../etc/passwd"))

    def test_a_screenshot_reaches_the_model_but_the_history_keeps_only_its_number(self) -> None:
        friday, model = self.friday([[text("截图里是 Lab 3 的截止：周四 18:00。")]])
        picture = uploads.save(PNG)
        cid = friday.conversations.create()
        done = collect(friday.turn(cid, "这是什么", images=[picture["id"]]))[-1]
        self.assertEqual(done["reply"], "截图里是 Lab 3 的截止：周四 18:00。")

        sent = json.dumps(model.inputs[-1], ensure_ascii=False, default=str)
        self.assertIn("data:image/png;base64,", sent)  # 模型真的看到了图
        import asyncio
        kept = json.dumps(asyncio.run(friday.conversations.session(cid).get_items()), ensure_ascii=False)
        self.assertIn(picture["url"], kept)
        self.assertNotIn("base64", kept)  # 对话历史里只有编号，不会越存越大
        his = friday.conversations.thread()[0]
        self.assertEqual(his["images"], [{"id": picture["id"], "url": picture["url"]}])

    def test_claude_sees_the_picture_before_the_words(self) -> None:
        url = uploads.data_url(uploads.save(PNG)["url"])
        messages = claude.to_messages([{"role": "user", "content": [
            {"type": "input_text", "text": "这是什么"}, {"type": "input_image", "image_url": url, "detail": "auto"}]}])
        blocks = messages[0]["content"]
        self.assertEqual([b["type"] for b in blocks], ["image", "text"])
        self.assertEqual(blocks[0]["source"]["media_type"], "image/png")

    def test_upload_and_send_through_the_api(self) -> None:
        friday, _ = self.friday([[text("看到了。")]])
        with patch.object(main, "friday", friday):
            client = TestClient(main.app)
            picture = client.post("/api/uploads", files={"file": ("shot.png", PNG, "image/png")}).json()
            self.assertEqual(client.get(picture["url"]).content, PNG)
            self.assertEqual(client.post("/api/uploads", files={"file": ("x.txt", b"hello", "text/plain")}).status_code, 400)
            only_a_picture = client.post("/api/chat/stream", json={"message": "", "images": [picture["id"]]})
            self.assertIn("看到了。", only_a_picture.text)
            self.assertEqual(client.post("/api/chat/stream", json={"message": "  "}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
