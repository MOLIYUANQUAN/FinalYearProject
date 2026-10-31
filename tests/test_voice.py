"""按住说话：一趟上传，转写完立刻接着回答；默认文字回，他说「念给我听」才出声；整段转写用最准的模型，用不了依次退回。"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import openai
from fastapi.testclient import TestClient

from tests.fake_model import text
from tests.helpers import SandboxTestCase

import src.main as main
from src import voice


def sse(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


class VoiceAskTests(SandboxTestCase):
    def setUp(self) -> None:
        super().setUp()
        friday, _ = self.friday([[text("明天下午两点见导师。")]])
        patcher = patch.object(main, "friday", friday)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)

    def ask(self, heard: str):
        with patch.object(voice, "transcribe", return_value=heard):
            return self.client.post("/api/voice/ask", files={"file": ("speech.webm", b"audio", "audio/webm")})

    def test_heard_first_then_the_answer_in_one_request(self) -> None:
        events = sse(self.ask("明天下午有什么"))
        self.assertEqual(events[0], {"type": "heard", "text": "明天下午有什么", "spoken": False})
        self.assertEqual(events[-1]["reply"], "明天下午两点见导师。")

    def test_only_reads_aloud_when_asked(self) -> None:
        self.assertTrue(sse(self.ask("念给我听明天有什么"))[0]["spoken"])

    def test_nothing_heard(self) -> None:
        self.assertEqual(self.ask("").status_code, 400)


class TranscribeTests(unittest.TestCase):
    def test_the_most_accurate_model_with_his_words_then_older_ones_as_fallback(self) -> None:
        client = MagicMock()
        missing = openai.NotFoundError("no model", response=MagicMock(status_code=404), body=None)
        refused = openai.BadRequestError("bad", response=MagicMock(status_code=400), body=None)
        client.audio.transcriptions.create.side_effect = [missing, refused, MagicMock(text=" 在吗 ")]
        with patch.object(voice, "_client", return_value=client):
            self.assertEqual(voice.transcribe(b"audio", "speech.webm"), "在吗")
        first, second, third = client.audio.transcriptions.create.call_args_list
        self.assertEqual(first.kwargs["model"], "gpt-transcribe")
        self.assertIn("Friday", first.kwargs["extra_body"]["keywords"])
        self.assertEqual(first.kwargs["extra_body"]["languages"], ["zh", "en"])
        self.assertNotIn("prompt", first.kwargs)
        self.assertEqual(second.kwargs["model"], "gpt-4o-transcribe")
        self.assertIn("Friday", second.kwargs["prompt"])
        self.assertEqual(third.kwargs["model"], "whisper-1")

    def test_when_every_model_refuses_the_error_reaches_him(self) -> None:
        client = MagicMock()
        missing = openai.NotFoundError("no model", response=MagicMock(status_code=404), body=None)
        client.audio.transcriptions.create.side_effect = [missing, missing, missing]
        with patch.object(voice, "_client", return_value=client), self.assertRaises(openai.NotFoundError):
            voice.transcribe(b"audio", "speech.webm")


if __name__ == "__main__":
    unittest.main()
