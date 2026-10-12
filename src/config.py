"""Baseline 配置：路径、演示用「今天」、API Key 检查。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CALENDAR_PATH = DATA_DIR / "calendar.json"
NOTES_DIR = DATA_DIR / "notes"
STATIC_DIR = ROOT_DIR / "static"

# 演示固定「今天」：相对词「明天」→ 2026-10-13（日历里有 FYP meeting）
# 不随系统时钟变化，保证 demo 可复现。详见 README。
MOCK_TODAY = "2026-10-12"
MOCK_TOMORROW = "2026-10-13"

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


def load_env() -> None:
    load_dotenv(ROOT_DIR / ".env")


def require_openai_api_key() -> str:
    """返回 OPENAI_API_KEY；缺失时抛出清晰错误。"""
    load_env()
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "缺少 OPENAI_API_KEY。请复制 .env.example 为 .env 并填入有效的 OpenAI API Key。"
        )
    return key
