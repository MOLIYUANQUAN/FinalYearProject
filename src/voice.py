"""语音：Whisper 听写 + TTS 播报。按一下说完再转，不做永远在听。"""

from __future__ import annotations

import io
import os
import re

from openai import OpenAI

from src.config import load_env, require_openai_api_key

# Whisper 单文件上限 25MB；网页侧再卡短一点
MAX_AUDIO_BYTES = 12 * 1024 * 1024
# 播报别念太长：长回复仍显示全文，只念前面
MAX_SPEAK_CHARS = 800


def _client() -> OpenAI:
    return OpenAI(api_key=require_openai_api_key())


def transcribe(audio: bytes, filename: str = "audio.webm") -> str:
    """把一段录音转成文字；空录音或听不清就返回空字符串。"""
    if not audio:
        raise RuntimeError("没有录到声音。")
    if len(audio) > MAX_AUDIO_BYTES:
        raise RuntimeError("这段太长了，短一点再说。")
    name = (filename or "audio.webm").strip() or "audio.webm"
    if "/" in name or "\\" in name:
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
    bio = io.BytesIO(audio)
    bio.name = name
    result = _client().audio.transcriptions.create(
        model="whisper-1",
        file=bio,
    )
    return (result.text or "").strip()


def speak(text: str) -> bytes:
    """把回复念出来，返回 mp3 字节。"""
    load_env()
    cleaned = _for_speech(text)
    if not cleaned:
        raise RuntimeError("没有可念的文字。")
    voice = (os.getenv("FRIDAY_TTS_VOICE") or "onyx").strip() or "onyx"
    model = (os.getenv("FRIDAY_TTS_MODEL") or "tts-1").strip() or "tts-1"
    response = _client().audio.speech.create(
        model=model,
        voice=voice,
        input=cleaned,
        response_format="mp3",
    )
    return response.content


def _for_speech(text: str) -> str:
    raw = (text or "").strip()
    raw = re.sub(r"```[\s\S]*?```", " ", raw)
    raw = re.sub(r"`([^`]+)`", r"\1", raw)
    raw = re.sub(r"\*\*(.+?)\*\*", r"\1", raw)
    raw = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw)
    raw = re.sub(r"https?://\S+", " ", raw)
    raw = re.sub(r"[#*_>•]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if len(raw) > MAX_SPEAK_CHARS:
        raw = raw[: MAX_SPEAK_CHARS - 1].rstrip() + "…"
    return raw
