"""语音：Whisper 听写 + TTS 播报。按一下说完再转，不做永远在听。"""

from __future__ import annotations

import io
import os
import re

import requests
from openai import OpenAI

from src.config import load_env, require_openai_api_key

# Whisper 单文件上限 25MB；网页侧再卡短一点
MAX_AUDIO_BYTES = 12 * 1024 * 1024
TRANSCRIBE_MODEL = os.getenv("FRIDAY_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
# 播报别念太长：长回复仍显示全文，只念前面
MAX_SPEAK_CHARS = 800

# 有 ELEVENLABS_API_KEY 时用 ElevenLabs（更自然）；否则退回 OpenAI
DEFAULT_ELEVEN_VOICE = "5VD7EFo2dAP623ZPyqSO"
DEFAULT_ELEVEN_MODEL = "eleven_v4"
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_TTS_VOICE = "marin"
ENGLISH_STYLE = (
    "Voice: a young woman, soft and warm, quietly confident. "
    "Delivery: relaxed and conversational, like talking to someone she knows well; "
    "natural rhythm with small pauses, a slight smile in the voice. "
    "Never sound like a newsreader, a phone menu, or a movie trailer."
)
CHINESE_STYLE = (
    "Voice: a young woman, soft and warm, quietly confident. "
    "Speak natural, native Mandarin Chinese, the way she talks to someone she knows well: "
    "relaxed and conversational, natural rhythm with small pauses, a slight smile in the voice. "
    "No broadcast tone, no customer-service tone, no exaggerated emotion."
)

TIME = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
TIME_RANGE = re.compile(
    r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)\s*[–—~-]\s*([01]?\d|2[0-3]):([0-5]\d)(?![\d:])"
)
LIST_MARK = re.compile(r"^\s*(?:[-*•·]|\d+[)、]|\d+\.(?=\s))\s*")


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
    import openai

    # 比 whisper-1 快、也更准；把他常说的专有名词告诉它，「Kilburn」「COMP34111」就不会听成别的
    for model in (TRANSCRIBE_MODEL, "whisper-1"):
        bio = io.BytesIO(audio)
        bio.name = name
        try:
            result = _client().audio.transcriptions.create(model=model, file=bio, prompt=_vocabulary())
        except (openai.NotFoundError, openai.BadRequestError) as exc:
            if model == "whisper-1":
                raise
            print(f"[WARN] {model} unavailable ({exc}); falling back to whisper-1")
            continue
        return (result.text or "").strip()
    return ""


def vocabulary() -> list[str]:
    """他常说的专有名词：Friday、他的名字、课程代码、常去的楼——从档案里取，没有就给几个固定的。"""
    from src.context import his_name, module_names

    words = ["Friday", his_name() or "Zeep", "FYP", "Kilburn", "Cursor", *module_names().keys()]
    return [w for w in words if w]


def _vocabulary() -> str:
    """转写提示（整段录音那条路）。"""
    return "、".join(vocabulary())


# 边说边出字最近一次没成的原因（资料页「语音」那行看得到）；成了一次就清掉
_live_problem = ""


def note_live_problem(reason: str) -> None:
    global _live_problem
    _live_problem = (reason or "").splitlines()[0][:80] if reason else ""


def live_problem() -> str:
    return _live_problem


# 他明说要听才念：和页面上 wantsVoice 是同一套说法
WANTS_VOICE = re.compile(r"听听|听你|你的声音|念给|读给|说两句|说句话|hear (your )?voice|speak (to me|up)|say something", re.I)


def wants_voice(text: str) -> bool:
    return bool(WANTS_VOICE.search(text or ""))


def speak(text: str) -> bytes:
    """把一句回复念出来，返回 mp3 字节。"""
    load_env()
    chinese = _is_chinese(text)
    cleaned = _for_speech(text, chinese)
    if not cleaned:
        raise RuntimeError("没有可念的文字。")
    if (os.getenv("ELEVENLABS_API_KEY") or "").strip():
        return _speak_eleven(cleaned, chinese)
    return _speak_openai(cleaned, chinese)


def _speak_eleven(text: str, chinese: bool) -> bytes:
    key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    voice = (os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_ELEVEN_VOICE).strip() or DEFAULT_ELEVEN_VOICE
    model = (os.getenv("ELEVENLABS_MODEL") or DEFAULT_ELEVEN_MODEL).strip() or DEFAULT_ELEVEN_MODEL
    payload: dict = {
        "text": text,
        "model_id": model,
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.75,
            "style": 0.15,
            "use_speaker_boost": True,
        },
    }
    # v4 / flash 认 language_code；multilingual_v2 会忽略
    if model != "eleven_multilingual_v2":
        payload["language_code"] = "zh" if chinese else "en"
    res = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        json=payload,
        timeout=60,
    )
    if res.status_code != 200:
        detail = (res.text or "").strip()[:200] or f"HTTP {res.status_code}"
        raise RuntimeError(f"ElevenLabs 没念出来：{detail}")
    return res.content


def _speak_openai(text: str, chinese: bool) -> bytes:
    model = (os.getenv("FRIDAY_TTS_MODEL") or DEFAULT_TTS_MODEL).strip() or DEFAULT_TTS_MODEL
    voice = (os.getenv("FRIDAY_TTS_VOICE") or DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE
    style = (os.getenv("FRIDAY_TTS_INSTRUCTIONS") or (CHINESE_STYLE if chinese else ENGLISH_STYLE)).strip()
    kwargs: dict = {"model": model, "voice": voice, "input": text, "response_format": "mp3"}
    if style and model.startswith("gpt-"):
        kwargs["instructions"] = style
    return _client().audio.speech.create(**kwargs).content


def _is_chinese(text: str) -> bool:
    han = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    return han > 0 and han * 3 >= latin


def _period(hour: int) -> str:
    return "凌晨" if hour < 5 else "上午" if hour < 12 else "中午" if hour < 13 else "下午" if hour < 18 else "晚上"


def _say_clock(hour: int, minute: int, *, period: bool = True) -> str:
    """「14:30」说成「下午2点半」。"""
    tail = "点" if minute == 0 else "点半" if minute == 30 else f"点{minute}分"
    return f"{_period(hour) if period else ''}{hour - 12 if hour > 12 else hour or 12}{tail}"


def _say_range(match: re.Match) -> str:
    h1, m1, h2, m2 = (int(x) for x in match.groups())
    return f"{_say_clock(h1, m1)}到{_say_clock(h2, m2, period=_period(h1) != _period(h2))}"


def _join(lines: list[str], chinese: bool) -> str:
    """一行一件事的写法，连成说出口的句子。"""
    out = ""
    for line in lines:
        if out and out[-1] not in "。！？!?；;，,：:….":
            out += "。" if chinese else "."
        out += line if chinese or not out else " " + line
    return out


def _for_speech(text: str, chinese: bool) -> str:
    """写给眼睛看的回复改成念给耳朵听的：去掉符号和清单，中文里的钟点说成「下午三点半」。"""
    raw = (text or "").replace("\u00a0", " ")
    raw = re.sub(r"```[\s\S]*?```", " ", raw)
    raw = re.sub(r"`([^`]+)`", r"\1", raw)
    raw = re.sub(r"\*\*(.+?)\*\*", r"\1", raw)
    raw = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw)
    raw = re.sub(r"https?://\S+", " ", raw)
    raw = _join([line for line in (LIST_MARK.sub("", x).strip() for x in raw.splitlines()) if line], chinese)
    raw = re.sub(r"[#*_>•]+", " ", raw)
    if chinese:
        raw = raw.replace("·", "，")
        raw = TIME_RANGE.sub(_say_range, raw)
        raw = TIME.sub(lambda m: _say_clock(int(m[1]), int(m[2])), raw)
        raw = re.sub(r"\s*([，。！？；：])\s*", r"\1", raw)
    else:
        raw = raw.replace("·", ", ")
    raw = re.sub(r"\s+", " ", raw).strip()
    if len(raw) > MAX_SPEAK_CHARS:
        raw = raw[: MAX_SPEAK_CHARS - 1].rstrip() + "…"
    return raw
