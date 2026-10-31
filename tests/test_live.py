"""按住说话时边说边出字：页面 ↔ Friday ↔ 本机一个按脚本回话的「OpenAI 实时转写」，真的走 WebSocket。

测：发给 OpenAI 的设置（模型、24kHz PCM、不自动断句）、声音原样转过去、字一段段回到页面、松手拿到整句、
出错时页面收到 error（退回老办法）、没登录连不上、拿到整句后不再转写录音。不联网。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.server import serve

from tests.fake_model import text
from tests.helpers import SandboxTestCase

import src.main as main
from src import live, voice

DELTA = live.DELTA


class FakeRealtime:
    """本机的「OpenAI 实时转写」：每次连上都按同一份脚本，每收到一块声音回一段字；收到 commit 回整句。"""

    def __init__(self, words: list[str], *, refuse: str = "", finish: bool = True) -> None:
        self.words = list(words)
        self.refuse = refuse
        self.finish = finish
        self.seen: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}
        self.ready = threading.Event()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run, daemon=True).start()
        self.ready.wait(5)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._serve())
        finally:
            self.loop.close()

    async def _serve(self) -> None:
        async with serve(self._handle, "127.0.0.1", 0) as server:
            self.url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1/realtime?intent=transcription"
            self.stop = self.loop.create_future()
            self.ready.set()
            await self.stop

    async def _handle(self, ws: Any) -> None:
        self.headers = dict(ws.request.headers)
        words, said = list(self.words), []
        async for raw in ws:
            event = json.loads(raw)
            self.seen.append(event)
            if event["type"] == "session.update" and self.refuse:
                await ws.send(json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": self.refuse}}))
            elif event["type"] == "input_audio_buffer.append" and words:
                said.append(words.pop(0))
                await ws.send(json.dumps({"type": DELTA, "item_id": "item_1", "content_index": 0, "delta": said[-1]}))
            elif event["type"] == "input_audio_buffer.commit" and self.finish:
                await ws.send(json.dumps({"type": live.COMPLETED, "item_id": "item_1", "content_index": 0,
                                          "transcript": "".join(said)}))

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.stop.set_result, None)


class LiveWordsTests(SandboxTestCase):
    def setUp(self) -> None:
        super().setUp()
        for patcher in (
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "NO_PROXY": "127.0.0.1,localhost",
                                    "no_proxy": "127.0.0.1,localhost"}),
            patch.object(voice, "_live_problem", ""),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)

    def openai(self, words: list[str], **kwargs: Any) -> FakeRealtime:
        server = FakeRealtime(words, **kwargs)
        self.addCleanup(server.close)
        patcher = patch.object(live, "URL", server.url)
        patcher.start()
        self.addCleanup(patcher.stop)
        return server

    def test_words_come_back_while_he_talks_and_the_whole_line_on_release(self) -> None:
        server = self.openai(["明天", "下午三点", "见导师"])
        chunks = [bytes([i]) * 4800 for i in range(3)]  # 每块 0.1 秒、24kHz 16 位
        with self.client.websocket_connect("/api/voice/live") as ws:
            got = []
            for chunk in chunks:
                ws.send_bytes(chunk)
                got.append(ws.receive_json())
            ws.send_json({"type": "end"})
            done = ws.receive_json()
        self.assertEqual([g["text"] for g in got], ["明天", "下午三点", "见导师"])
        self.assertEqual(done, {"type": "done", "text": "明天下午三点见导师"})

        setup = server.seen[0]
        self.assertEqual(setup["type"], "session.update")
        session = setup["session"]
        self.assertEqual(session["type"], "transcription")
        heard = session["audio"]["input"]
        self.assertEqual(heard["format"], {"type": "audio/pcm", "rate": 24000})
        self.assertIsNone(heard["turn_detection"])
        self.assertEqual(heard["transcription"]["model"], "gpt-live-transcribe")
        self.assertEqual(heard["transcription"]["languages"], ["zh", "en"])
        self.assertIn("Friday", heard["transcription"]["keywords"])
        sent = [base64.b64decode(e["audio"]) for e in server.seen if e["type"] == "input_audio_buffer.append"]
        self.assertEqual(sent, chunks)
        self.assertEqual(server.seen[-1]["type"], "input_audio_buffer.commit")
        self.assertEqual(server.headers.get("authorization"), "Bearer sk-test")

    def test_when_openai_refuses_the_page_hears_error_and_her_page_says_why(self) -> None:
        self.openai([], refuse="Unknown parameter: 'session.audio.input.transcription.keywords'.")
        with self.client.websocket_connect("/api/voice/live") as ws:
            ws.send_bytes(b"\0" * 4800)
            said = ws.receive_json()
        self.assertEqual(said["type"], "error")
        self.assertIn("keywords", voice.live_problem())
        row = next(c for c in self.client.get("/api/me").json()["connections"] if c["name"].startswith("语音"))
        self.assertFalse(row["ok"])
        self.assertIn("松手后照常转写", row["note"])

    def test_no_whole_line_in_time_is_an_error_not_a_hang(self) -> None:
        self.openai(["明天"], finish=False)
        with patch.object(live, "FINISH_S", 0.3), self.client.websocket_connect("/api/voice/live") as ws:
            ws.send_bytes(b"\0" * 4800)
            self.assertEqual(ws.receive_json()["text"], "明天")
            ws.send_json({"type": "end"})
            self.assertEqual(ws.receive_json()["type"], "error")
        self.assertEqual(voice.live_problem(), "松手后没等到整句")

    def test_cancel_closes_without_asking_for_a_line(self) -> None:
        server = self.openai(["算了"])
        with self.client.websocket_connect("/api/voice/live") as ws:
            ws.send_bytes(b"\0" * 4800)
            ws.receive_json()
            ws.send_json({"type": "cancel"})
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()
        self.assertNotIn("input_audio_buffer.commit", [e["type"] for e in server.seen])

    def test_without_logging_in_the_socket_is_refused(self) -> None:
        self.openai([])
        with patch("src.access.get_access_token", return_value="secret"):
            with self.assertRaises(WebSocketDisconnect) as refused:
                with self.client.websocket_connect("/api/voice/live") as ws:
                    ws.receive_json()
        self.assertEqual(refused.exception.code, 1008)

    def test_another_site_cannot_open_it(self) -> None:
        self.openai([])
        with self.assertRaises(WebSocketDisconnect) as refused:
            with self.client.websocket_connect("/api/voice/live", headers={"origin": "https://evil.example"}) as ws:
                ws.receive_json()
        self.assertEqual(refused.exception.code, 1008)


class SendingTheLineTests(SandboxTestCase):
    def test_with_the_line_in_hand_the_recording_is_not_transcribed_again(self) -> None:
        service, model = self.friday([[text("好，三点。")]])
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}), patch.object(main, "friday", service), \
                patch.object(voice, "transcribe", side_effect=AssertionError("should not transcribe")):
            res = TestClient(main.app).post("/api/voice/ask", data={"text": "明天下午三点见导师"})
        events = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[0], {"type": "heard", "text": "明天下午三点见导师", "spoken": False})
        self.assertEqual(events[-1]["reply"], "好，三点。")

    def test_neither_words_nor_recording_asks_again(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            res = TestClient(main.app).post("/api/voice/ask", data={"text": "  "})
        self.assertEqual(res.status_code, 400)
