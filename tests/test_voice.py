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


class TidyTests(SandboxTestCase):
    """转写完按上下文改错字：用最近几句和他常说的词；小模型乱来（答话、删光）就用原样。"""

    def tidy(self, said: str, text: str = "在这里看到大会直接出字吗", context: str = "") -> tuple[str, str]:
        with patch.dict("os.environ", {"FRIDAY_TIDY_SPEECH": "1", "ANTHROPIC_API_KEY": "sk-ant-test"}), \
                patch("src.claude.ask", return_value=said) as asked:
            out = voice.tidy(text, context)
        return out, asked.call_args.args[1] if asked.call_args else ""

    def test_a_homophone_is_fixed_with_the_conversation_as_context(self) -> None:
        out, prompt = self.tidy("在这里看到它会直接出字吗？", context="他：会直接出字了吗\n她：会，按住就出")
        self.assertEqual(out, "在这里看到它会直接出字吗？")
        self.assertIn("会直接出字了吗", prompt)
        self.assertIn("Friday", prompt)
        self.assertIn("在这里看到大会直接出字吗", prompt)

    def test_an_answer_instead_of_a_fix_is_ignored(self) -> None:
        out, _ = self.tidy("会的！按住麦克风说话，松手之后字就会出来，而且我会马上回答你提出的问题。")
        self.assertEqual(out, "在这里看到大会直接出字吗")
        self.assertEqual(self.tidy("好")[0], "在这里看到大会直接出字吗")

    def test_when_the_model_fails_the_words_stay_as_heard(self) -> None:
        with patch.dict("os.environ", {"FRIDAY_TIDY_SPEECH": "1", "ANTHROPIC_API_KEY": "sk-ant-test"}), \
                patch("src.claude.ask", side_effect=TimeoutError("slow")):
            self.assertEqual(voice.tidy("明天三点"), "明天三点")

    def test_the_heard_line_is_the_fixed_one(self) -> None:
        friday, _ = self.friday([[text("会。")]])
        with patch.object(main, "friday", friday), patch.object(voice, "transcribe", return_value="大会直接出字吗"), \
                patch.object(voice, "tidy", return_value="它会直接出字吗？") as tidied:
            events = sse(TestClient(main.app).post("/api/voice/ask", files={"file": ("speech.m4a", b"audio", "audio/mp4")}))
        self.assertEqual(events[0]["text"], "它会直接出字吗？")
        self.assertEqual(tidied.call_args.args[0], "大会直接出字吗")
        self.assertEqual(friday.conversations.thread()[0]["content"], "它会直接出字吗？")


class HerPageTests(SandboxTestCase):
    def test_her_page_says_which_model_transcribed(self) -> None:
        client = MagicMock()
        client.audio.transcriptions.create.return_value = MagicMock(text="在吗")
        with patch.object(voice, "_client", return_value=client), patch.object(voice, "last_model", ""):
            voice.transcribe(b"audio", "speech.webm")
            rows = TestClient(main.app).get("/api/me").json()["connections"]
        row = next(r for r in rows if r["name"].startswith("语音"))
        self.assertEqual(row["note"], "正常 · 转写用 gpt-transcribe")


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
