"""按住说话时边说边出字（只是预览）。

页面按住那一刻连上 /api/voice/live，把麦克风的声音（24kHz、16 位 PCM）一小块一小块发来；这里转给 OpenAI 的实时转写
（gpt-live-transcribe），字一出来就送回页面，填进他的气泡。松手（或上滑取消）页面就断开。

发出去的那句不用这里的字：实时转写为了快只能边听边猜，看不到后面的话，同音字常错（「它会」听成「大会」）。
松手后整段录音交给最准的整段转写（voice.transcribe），以那句为准，气泡里的预览会被换掉。

key 只在服务端。这边出了问题就发 {"type": "error"}：他只是少看到边说边出的字，资料页「语音」那行写原因。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect

from src import voice
from src.config import require_openai_api_key

MODEL = os.getenv("FRIDAY_LIVE_MODEL", "gpt-live-transcribe")
URL = os.getenv("FRIDAY_REALTIME_URL", "wss://api.openai.com/v1/realtime?intent=transcription")
RATE = 24_000  # 实时转写只收 24kHz

DELTA = "conversation.item.input_audio_transcription.delta"
FAILED = "conversation.item.input_audio_transcription.failed"


def session() -> dict[str, Any]:
    """这个模型不支持自动断句（turn_detection 只能是 null）：一直出字。"""
    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": RATE},
                    "noise_reduction": {"type": "near_field"},
                    "transcription": {"model": MODEL, "languages": ["zh", "en"], "keywords": voice.vocabulary()},
                    "turn_detection": None,
                }
            },
        },
    }


def _reason(event: dict[str, Any]) -> str:
    error = event.get("error") if isinstance(event.get("error"), dict) else {}
    return str(error.get("message") or error.get("code") or event.get("type") or "unknown")[:200]


async def relay(page: WebSocket) -> None:
    """一次按住：页面的声音 → OpenAI；OpenAI 的字 → 页面。页面断开就结束。"""
    await page.accept()
    try:
        key = require_openai_api_key()
        async with connect(URL, additional_headers={"Authorization": f"Bearer {key}"}, open_timeout=8,
                           max_size=None) as upstream:
            await upstream.send(json.dumps(session()))

            async def up() -> None:
                while True:
                    message = await page.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    if message.get("bytes"):
                        audio = base64.b64encode(message["bytes"]).decode("ascii")
                        await upstream.send(json.dumps({"type": "input_audio_buffer.append", "audio": audio}))

            async def down() -> None:
                async for raw in upstream:
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind == DELTA and event.get("delta"):
                        await page.send_json({"type": "delta", "text": event["delta"]})
                        voice.note_live_problem("")
                    elif kind in (FAILED, "error"):
                        raise RuntimeError(_reason(event))
                raise RuntimeError("OpenAI 那边断开了")

            listening = asyncio.create_task(down())
            sending = asyncio.create_task(up())
            try:
                await asyncio.wait({listening, sending}, return_when=asyncio.FIRST_COMPLETED)
                if listening.done():
                    listening.result()
            finally:
                for task in (listening, sending):
                    task.cancel()
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        reason = str(exc) or type(exc).__name__
        print(f"[WARN] live transcription: {reason}")
        voice.note_live_problem(reason)
        try:
            await page.send_json({"type": "error", "message": reason[:200]})
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass
