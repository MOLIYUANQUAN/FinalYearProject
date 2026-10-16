"""打开时的「今天」：服务端读真实日历，原样排成卡片；再挑出此刻最该说的一件事，模型只把它说成一句话。"""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta
from typing import Any

from src import agenda
from src.agenda import Timed, day_label, title, when
from src.config import effective_now
from src.context import greeting, his_name, weekday_zh

# 开场用的日历最多旧 1 分钟：卡片是他最先看到、最信的东西
CARD_FRESH_S = 60
# 值得提前说的事：见导师、开会、截止、考试
IMPORTANT = re.compile(
    r"导师|会议|开会|例会|见面|截止|考试|面试|答辩|mentor|supervisor|meeting|deadline|due|exam|interview|viva",
    re.IGNORECASE,
)


def _day_word(day: date, today: date) -> str:
    if day == today:
        return "今天"
    if day == today + timedelta(days=1):
        return "明天"
    return day_label(day)


def _span(delta: timedelta) -> str:
    hours, minutes = divmod(max(0, int(delta.total_seconds() // 60)), 60)
    if not hours:
        return f"{minutes} 分钟"
    return f"{hours} 小时" + (f" {minutes} 分钟" if minutes else "")


def _place(event: dict[str, Any]) -> str:
    """卡片上的地点：链接只写「在线」，长地名截断。"""
    place = agenda.where(event)
    return "在线" if "://" in place else place[:60]


def _at(event: dict[str, Any]) -> str:
    place = _place(event)
    return f"（{place}）" if place else ""


def _row(event: dict[str, Any], start: datetime, end: datetime | None, *, now: bool = False) -> dict[str, Any]:
    return {"time": when(start, end), "title": title(event), "where": _place(event), "now": now}


def _all_day_rows(titles: list[str]) -> list[dict[str, Any]]:
    return [{"time": "全天", "title": name, "where": "", "now": False} for name in titles]


def _sections(now: datetime, timed: list[Timed], all_day: list[tuple[date, str]]) -> list[dict[str, Any]]:
    """他眼前的卡片：今天还剩的、明天的；两天都空就给下一件。"""
    today = now.date()
    tomorrow = today + timedelta(days=1)
    remaining = [(s, e, ev) for s, e, ev in timed if s.date() == today and (e or s) > now]
    finished = sum(1 for s, e, _ in timed if s.date() == today and (e or s) <= now)
    upcoming = [(s, e, ev) for s, e, ev in timed if s.date() == tomorrow]

    sections = [
        {
            "label": "今天",
            "meta": f"已结束 {finished} 项" if finished else "",
            "rows": _all_day_rows([t for d, t in all_day if d == today])
            + [_row(ev, s, e, now=s <= now) for s, e, ev in remaining],
            "empty": "都结束了" if finished else "没有安排",
        },
        {
            "label": f"明天 · {weekday_zh(tomorrow)}",
            "meta": "",
            "rows": _all_day_rows([t for d, t in all_day if d == tomorrow]) + [_row(ev, s, e) for s, e, ev in upcoming],
            "empty": "没有安排",
        },
    ]
    if not remaining and not upcoming:
        later = next((item for item in timed if item[0].date() > tomorrow), None)
        if later:
            start, end, event = later
            sections.append(
                {"label": f"下一件 · {day_label(start.date())}", "meta": "", "rows": [_row(event, start, end)], "empty": ""}
            )
        else:
            sections.append({"label": "到下周日", "meta": "", "rows": [], "empty": "都没有安排"})
    return sections


def _focus(now: datetime, timed: list[Timed], all_day: list[tuple[date, str]]) -> str:
    """此刻最该说的一件事。挑哪件、相差多久都在这里算好，模型只负责说成一句话。"""
    today = now.date()
    tomorrow = today + timedelta(days=1)
    current = next(((s, e, ev) for s, e, ev in timed if e and s <= now < e), None)
    upcoming = [(s, e, ev) for s, e, ev in timed if s > now]
    soon = upcoming[0] if upcoming else None

    if soon is None:
        free = "一直到下周日都没有安排"
    elif soon[0].date() == today:
        free = f"现在到 {soon[0]:%H:%M} 都空着（{_span(soon[0] - now)}）"
    elif soon[0].date() == tomorrow:
        free = "今天后面都空着"
    else:
        gap = (soon[0].date() - today).days
        free_days = {(today + timedelta(days=i)).weekday() for i in range(gap)}
        if {5, 6} <= free_days and gap <= 3:
            head = "整个周末都空着"
        elif gap == 2:
            head = "今天和明天都空着"
        else:
            head = "这几天都空着"
        free = f"{head}，一直到{agenda.weekday_word(soon[0].date(), today)} {soon[0]:%H:%M}"

    if current and soon and soon[0] - current[1] <= timedelta(minutes=15):
        gap = soon[0] - current[1]
        between = "紧接着" if gap <= timedelta(0) else f"只隔 {_span(gap)}"
        return (
            f"{title(current[2])}还剩 {_span(current[1] - now)}，"
            f"结束后{between}就是{title(soon[2])}{_at(soon[2])}"
        )
    if soon and soon[0].date() == today and soon[0] - now <= timedelta(hours=1):
        return f"{title(soon[2])} {_span(soon[0] - now)}后开始{_at(soon[2])}"
    for day, name in all_day:
        if today <= day <= tomorrow and IMPORTANT.search(name):
            return f"{_day_word(day, today)}全天：{name}；{free}"
    for start, _, event in upcoming:
        if start.date() <= tomorrow and IMPORTANT.search(title(event)):
            return f"接下来最要紧的是{_day_word(start.date(), today)} {start:%H:%M} 的{title(event)}{_at(event)}；{free}"
    if soon and soon[0].date() == today:
        return f"{free}，之后是{title(soon[2])}"
    if soon and soon[0].date() == tomorrow:
        return f"{free}；明天第一件是 {soon[0]:%H:%M} 的{title(soon[2])}"
    if soon:
        return f"{free} 的{title(soon[2])}"
    return free


def _prompt(now: datetime, focus: str) -> str:
    return "\n".join(
        [
            f"【此刻】{now.date().isoformat()} {weekday_zh(now)} {now:%H:%M}",
            f"【要说的事】{focus}",
            "",
            "他刚打开你，卡片上已经列着他的安排和问候。把【要说的事】说成一句自然的话（不超过 30 个字），"
            "像熟悉他的人随口一提。小建议只在真用得上时加（比如现在出发、提前准备要交的东西），用不上就不加。",
            "- 只说这一件事，不加别的事实；数字只能用上面写好的。",
            "- 说日子用「今天」「明天」或星期几；时间可以说成「下午 3 点」这样。",
            "- 不问候，不叫名字，不要问问题，不用 Markdown。",
        ]
    )


def today_view(now: datetime, events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """同一份日历：他眼前的卡片，和此刻最该说的那件事。"""
    timed, all_day = agenda.split(events)
    return _sections(now, timed, all_day), _focus(now, timed, all_day)


async def presence_input() -> tuple[dict[str, Any], str | None]:
    """返回（卡片，给模型的提示）：卡片立刻画出来，那句话随后流进来。日历没读到就没有那句话。"""
    now = effective_now()
    name = his_name()
    card: dict[str, Any] = {"hello": f"{greeting(now)}，{name}" if name else greeting(now), "sections": [], "error": ""}

    try:
        events, _ = await asyncio.to_thread(agenda.read, CARD_FRESH_S)
    except RuntimeError as exc:
        card["error"] = str(exc).splitlines()[0]
        return card, None
    except Exception:  # noqa: BLE001
        card["error"] = "日历这次没读到。"
        return card, None
    card["sections"], focus = today_view(now, events)
    return card, _prompt(now, focus)
