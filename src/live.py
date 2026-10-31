"""按住说话时边说边出字。

页面按住那一刻连上 /api/voice/live，把麦克风的声音（24kHz、16 位 PCM）一小块一小块发来；这里转给 OpenAI 的实时转写
（gpt-live-transcribe），字一出来就送回页面。松手时页面发 {"type": "end"}，这里让 OpenAI 收尾，把整句送回去，
页面拿这句去问她。上滑取消发 {"type": "cancel"}。

key 只在服务端。这边出了任何问题都发 {"type": "error"}：页面退回老办法（整段录音传上来再转），他只是少看到边说边出的字。
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
FINISH_S = 4.0  # 松手后最多等这么久拿整句；过了页面就用录音

DELTA = "conversation.item.input_audio_transcription.delta"
COMPLETED = "conversation.item.input_audio_transcription.completed"
FAILED = "conversation.item.input_audio_transcription.failed"


def session() -> dict[str, Any]:
    """这个模型不支持自动断句（turn_detection 只能是 null）：一直出字，松手由我们提交。"""
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
    """一次按住：页面的声音 → OpenAI；OpenAI 的字 → 页面。"""
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
                        raise WebSocketDisconnect()
                    if message.get("bytes"):
                        audio = base64.b64encode(message["bytes"]).decode("ascii")
                        await upstream.send(json.dumps({"type": "input_audio_buffer.append", "audio": audio}))
                        continue
                    command = json.loads(message.get("text") or "{}").get("type")
                    if command == "end":
                        await upstream.send(json.dumps({"type": "input_audio_buffer.commit"}))
                        return
                    if command == "cancel":
                        raise WebSocketDisconnect()

            async def down() -> None:
                async for raw in upstream:
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind == DELTA and event.get("delta"):
                        await page.send_json({"type": "delta", "text": event["delta"]})
                    elif kind == COMPLETED:
                        await page.send_json({"type": "done", "text": (event.get("transcript") or "").strip()})
                        voice.note_live_problem("")
                        return
                    elif kind in (FAILED, "error"):
                        raise RuntimeError(_reason(event))
                raise RuntimeError("OpenAI 那边断开了")

            listening = asyncio.create_task(down())
            sending = asyncio.create_task(up())
            try:
                await asyncio.wait({listening, sending}, return_when=asyncio.FIRST_COMPLETED)
                if listening.done():
                    listening.result()
                    return
                sending.result()  # 他取消了、页面断了：在这里抛出
                # 松手了：等整句
                await asyncio.wait_for(listening, FINISH_S)
            finally:
                for task in (listening, sending):
                    task.cancel()
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        reason = "松手后没等到整句" if isinstance(exc, TimeoutError) else (str(exc) or type(exc).__name__)
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
