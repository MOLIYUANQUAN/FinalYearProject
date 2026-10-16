"""配置：路径、演示日期、日历后端、API Key。"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CALENDAR_PATH = DATA_DIR / "calendar.json"
NOTES_DIR = DATA_DIR / "notes"
PERSONAL_DIR = DATA_DIR / "personal"
PROFILE_PATH = PERSONAL_DIR / "profile.md"
MAIL_DIR = DATA_DIR / "mail"
MAIL_MOCK_PATH = MAIL_DIR / "messages.json"
MEMORY_DIR = DATA_DIR / "memory"
MEMORY_FACTS_PATH = MEMORY_DIR / "facts.json"
USAGE_LOG_PATH = DATA_DIR / "usage" / "events.jsonl"
STATIC_DIR = ROOT_DIR / "static"
SECRETS_DIR = ROOT_DIR / "secrets"

# 演示固定「今天」：仅 mock 后端使用，保证 Demo 可复现。详见 README / docs。
MOCK_TODAY = "2026-10-12"
MOCK_TOMORROW = "2026-10-13"
MOCK_NOW_TIME = "09:00"

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

# calendar backend: mock | google
GOOGLE_CREDENTIALS_PATH = SECRETS_DIR / "credentials.json"
GOOGLE_TOKEN_PATH = SECRETS_DIR / "google_token.json"
GMAIL_TOKEN_PATH = SECRETS_DIR / "gmail_token.json"
OUTLOOK_TOKEN_PATH = SECRETS_DIR / "outlook_token.json"
GOOGLE_TASKS_TOKEN_PATH = SECRETS_DIR / "google_tasks_token.json"
TASKS_PATH = DATA_DIR / "tasks.json"


def load_env() -> None:
    load_dotenv(ROOT_DIR / ".env")


def get_calendar_backend() -> str:
    """返回日历后端：mock（默认）或 google。"""
    load_env()
    value = (os.getenv("CALENDAR_BACKEND") or "mock").strip().lower()
    if value not in {"mock", "google"}:
        raise RuntimeError(
            f"无效 CALENDAR_BACKEND={value!r}。请使用 mock 或 google。"
        )
    return value


def get_google_calendar_id() -> str:
    """Google 日历选择：selected（默认，网页勾选的全部）| primary | 具体 calendarId。"""
    load_env()
    return (os.getenv("GOOGLE_CALENDAR_ID") or "selected").strip() or "selected"


def get_mail_backend() -> str:
    """邮件后端：none | mock | gmail | outlook。"""
    load_env()
    value = (os.getenv("MAIL_BACKEND") or "none").strip().lower()
    if value not in {"none", "mock", "gmail", "outlook"}:
        raise RuntimeError(
            f"无效 MAIL_BACKEND={value!r}。请使用 none、mock、gmail 或 outlook。"
        )
    return value


def get_tasks_backend() -> str:
    """待办后端：none（默认，没接入就完全不出现）| mock | google。"""
    load_env()
    value = (os.getenv("TASKS_BACKEND") or "none").strip().lower()
    if value not in {"none", "mock", "google"}:
        raise RuntimeError(f"无效 TASKS_BACKEND={value!r}。请使用 none、mock 或 google。")
    return value


def get_outlook_client_id() -> str:
    load_env()
    return (os.getenv("OUTLOOK_CLIENT_ID") or "").strip()


def get_outlook_tenant() -> str:
    load_env()
    return (os.getenv("OUTLOOK_TENANT") or "organizations").strip() or "organizations"


def effective_today() -> str:
    """Agent 指令用的「今天」：mock 后端用固定日，google 用系统本地日。"""
    if get_calendar_backend() == "mock":
        return MOCK_TODAY
    return date.today().isoformat()


def effective_tomorrow() -> str:
    if get_calendar_backend() == "mock":
        return MOCK_TOMORROW
    return (date.today() + timedelta(days=1)).isoformat()


def effective_now() -> datetime:
    """Agent 眼中的「此刻」：mock 固定在 MOCK_TODAY 早上，google 用本地真实时间。"""
    if get_calendar_backend() == "mock":
        return datetime.fromisoformat(f"{MOCK_TODAY}T{MOCK_NOW_TIME}")
    return datetime.now().replace(second=0, microsecond=0)


def require_openai_api_key() -> str:
    """返回 OPENAI_API_KEY；缺失时抛出清晰错误。"""
    load_env()
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "缺少 OPENAI_API_KEY。请复制 .env.example 为 .env 并填入有效的 OpenAI API Key。"
        )
    return key
