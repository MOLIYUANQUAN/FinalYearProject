"""每轮都放进 Agent 脑子里的「认识你」：此刻 + 档案 + 记得的事。"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from src import memory_store
from src.config import PROFILE_PATH, effective_now

WEEKDAYS_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
MEMORY_INJECT_LIMIT = 40


def weekday_zh(day: date | datetime) -> str:
    return WEEKDAYS_ZH[day.weekday()]


def greeting(now: datetime) -> str:
    if 5 <= now.hour < 12:
        return "早上好"
    if 12 <= now.hour < 17:
        return "下午好"
    return "晚上好"


def his_name() -> str:
    """档案的第一个标题就是他的名字。"""
    if not PROFILE_PATH.is_file():
        return ""
    for line in PROFILE_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def module_names() -> dict[str, str]:
    """档案里「COMP34111 AI and Games」这样写过的课程名。"""
    if not PROFILE_PATH.is_file():
        return {}
    text = PROFILE_PATH.read_text(encoding="utf-8")
    return {code: name.strip() for code, name in re.findall(r"\b([A-Z]{4}\d{5})\s+([^,，;\n(（]+)", text)}


def now_block() -> str:
    now = effective_now()
    tomorrow = now.date() + timedelta(days=1)
    return "\n".join(
        [
            f"此刻：{now:%Y-%m-%d} {weekday_zh(now)} {now:%H:%M}（本地时间）",
            f"- 明天 = {tomorrow.isoformat()} {weekday_zh(tomorrow)}",
            "- 日历工具的日期用 YYYY-MM-DD，时间用 YYYY-MM-DDTHH:MM（24 小时制）",
            "- morning 05–12，afternoon 12–17，evening 17 点以后；已经结束的事件不算待办",
        ]
    )


def profile_block() -> str:
    if not PROFILE_PATH.is_file():
        return "他的档案：（暂无）"
    return "他的档案：\n" + PROFILE_PATH.read_text(encoding="utf-8").strip()


def memory_block() -> str:
    facts = memory_store.all_facts()
    if not facts:
        return "你记得的事：（还没有）"
    shown = facts[:MEMORY_INJECT_LIMIT]
    lines = [f"- [{f.get('id')}] {f.get('content')}" for f in shown]
    if len(facts) > len(shown):
        lines.append(f"（还有 {len(facts) - len(shown)} 条更早的，需要时用 search_memory 搜）")
    return "你记得的事（新的在前，方括号里是 id）：\n" + "\n".join(lines)
