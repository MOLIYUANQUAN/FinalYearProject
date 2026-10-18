"""打开时的「今天」：服务端读真实日历和待办，原样排成卡片，再算出此刻最该说的那一句。全程不经过模型。"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from typing import Any

from src import agenda, todos
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


def _there(event: dict[str, Any]) -> str:
    """要赶过去的地方；线上的不用说。"""
    place = _place(event)
    return f"，在{place}" if place and place != "在线" else ""


def _clock(moment: datetime) -> str:
    """说出口的钟点：「中午 12 点」「下午 3 点半」「晚上 7:15」。"""
    hour, minute = moment.hour, moment.minute
    period = "凌晨" if hour < 5 else "上午" if hour < 12 else "中午" if hour < 13 else "下午" if hour < 18 else "晚上"
    tail = "点" if minute == 0 else "点半" if minute == 30 else f":{minute:02d}"
    return f"{period}{hour - 12 if hour > 12 else hour or 12}{tail}"


def _spaced(text: str) -> str:
    """中文和英文、数字之间留一个空格。"""
    text = re.sub(r"([\u4e00-\u9fff])([A-Za-z0-9])", r"\1 \2", text)
    text = re.sub(r"([A-Za-z])([\u4e00-\u9fff])", r"\1 \2", text)
    # 数字和后面的「点」「分钟」之间用不换行空格：换行时不会把「6 点」拆成两行
    return re.sub(r"([0-9]) ?([\u4e00-\u9fff])", "\\1\u00a0\\2", text)


def _row(event: dict[str, Any], start: datetime, end: datetime | None, *, now: bool = False) -> dict[str, Any]:
    return {"time": when(start, end), "title": title(event), "where": _place(event), "now": now}


def _all_day_rows(titles: list[str]) -> list[dict[str, Any]]:
    return [{"time": "全天", "title": name, "where": "", "now": False} for name in titles]


def _task_section(tasks: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    """待办里过了截止的、今天和明天截止的；别的不占卡片。"""
    rows = []
    for task, due in todos.ordered(tasks):
        if due is None or due > today + timedelta(days=1):
            continue
        word = "今天" if due == today else "明天" if due > today else f"过了 {(today - due).days} 天"
        rows.append({"time": word, "title": task["title"], "where": "", "now": False})
    return {"label": "待办", "meta": "", "rows": rows, "empty": ""} if rows else None


def _sections(
    now: datetime, timed: list[Timed], all_day: list[tuple[date, str]], tasks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """他眼前的卡片：今天还剩的、明天的；两天都空就给下一件；最后是快到期的待办。"""
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
    due = _task_section(tasks, today)
    return sections + [due] if due else sections


def _names(titles: list[str]) -> str:
    return "、".join(titles) if len(titles) <= 3 else f"{'、'.join(titles[:2])} 等 {len(titles)} 件"


def _due_clause(now: datetime, tasks: list[dict[str, Any]]) -> str:
    """今天截止的待办；傍晚以后，也提一句明天截止的。"""
    today = now.date()
    pairs = todos.ordered(tasks)
    due = [task["title"] for task, day in pairs if day == today]
    if due:
        return _spaced(f"今天截止：{_names(due)}。")
    due = [task["title"] for task, day in pairs if day == today + timedelta(days=1)]
    return _spaced(f"明天截止：{_names(due)}。") if due and now.hour >= 17 else ""


def _say(now: datetime, timed: list[Timed], all_day: list[tuple[date, str]], tasks: list[dict[str, Any]]) -> str:
    """此刻最该说的那一句：马上要开始的课先说，其次是今天截止的待办，再是日历上的判断。"""
    sentence, urgent = _calendar_say(now, timed, all_day)
    due = _due_clause(now, tasks)
    return sentence + due if urgent else due + sentence


def _calendar_say(now: datetime, timed: list[Timed], all_day: list[tuple[date, str]]) -> tuple[str, bool]:
    """日历上此刻最该说的那件，和它是不是马上就要发生。挑哪件、相差多久都在这里算好。"""
    today = now.date()
    tomorrow = today + timedelta(days=1)
    current = next(((s, e, ev) for s, e, ev in timed if e and s <= now < e), None)
    upcoming = [(s, e, ev) for s, e, ev in timed if s > now]
    soon = upcoming[0] if upcoming else None
    spoken = agenda.spoken

    if current and soon and soon[0] - current[1] <= timedelta(minutes=15):
        gap = soon[0] - current[1]
        between = "紧接着是" if gap <= timedelta(0) else f"隔 {_span(gap)}就是"
        left = _span(current[1] - now)
        return _spaced(f"{spoken(current[2])}还剩 {left}，结束后{between}{spoken(soon[2])}{_there(soon[2])}。"), True
    if soon and soon[0].date() == today and soon[0] - now <= timedelta(hours=1):
        return _spaced(f"{spoken(soon[2])} {_span(soon[0] - now)}后开始{_there(soon[2])}。"), True

    if current:
        status = f"眼下的{spoken(current[2])}还剩 {_span(current[1] - now)}。"
    elif soon and soon[0].date() == today:
        status = f"{_clock(soon[0])}前都空着。"
    else:
        status = "今天后面都空着。"
    for day, name in all_day:
        if today <= day <= tomorrow and IMPORTANT.search(name):
            return _spaced(f"{_day_word(day, today)}全天：{name}。{status}"), False
    for start, _, event in upcoming:
        if start.date() <= tomorrow and IMPORTANT.search(title(event)):
            when_said = f"{_day_word(start.date(), today)}{_clock(start)}"
            return _spaced(f"最要紧的是{when_said}：{spoken(event)}{_there(event)}。{status}"), False

    if current:
        left = _span(current[1] - now)
        if soon and soon[0].date() == today:
            return _spaced(f"{spoken(current[2])}还剩 {left}，之后空到{_clock(soon[0])}。"), False
        return _spaced(f"{spoken(current[2])}还剩 {left}，之后今天就没别的了。"), False
    if soon is None:
        return "一直到下周日都没有安排。", False
    if soon[0].date() == today:
        return _spaced(f"接下来 {_span(soon[0] - now)}都空着。{_clock(soon[0])}：{spoken(soon[2])}。"), False
    if soon[0].date() == tomorrow:
        return _spaced(f"今天后面都空着。明天{_clock(soon[0])}：{spoken(soon[2])}。"), False
    gap = (soon[0].date() - today).days
    free_days = {(today + timedelta(days=i)).weekday() for i in range(gap)}
    sunday = agenda.this_sunday(today)
    if {5, 6} <= free_days and gap <= 3:
        head = "整个周末都空着"
    elif gap == 2:
        head = "今天和明天都空着"
    elif soon[0].date() > sunday > today:
        head = "这周后面都空着"
    else:
        head = "这几天都空着"
    next_day = agenda.weekday_word(soon[0].date(), today)
    return _spaced(f"{head}。{next_day}{_clock(soon[0])}：{spoken(soon[2])}。"), False


def today_view(
    now: datetime, events: list[dict[str, Any]], tasks: list[dict[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], str]:
    """同一份日历和待办：卡片分区、此刻那一句。"""
    timed, all_day = agenda.split(events)
    tasks = tasks or []
    say = _say(now, timed, all_day, tasks)
    return _sections(now, timed, all_day, tasks), say


def _reason(exc: BaseException, fallback: str) -> str:
    return str(exc).splitlines()[0] if isinstance(exc, RuntimeError) else fallback


async def presence_input() -> tuple[dict[str, Any], str]:
    """返回（卡片，那一句）；日历没读到时卡片上写原因，那一句为空。日历和待办同时读。"""
    now = effective_now()
    name = his_name()
    card: dict[str, Any] = {
        "hello": f"{greeting(now)}，{name}" if name else greeting(now),
        "sections": [],
        "error": "",
    }

    calendar, todo = await asyncio.gather(
        asyncio.to_thread(agenda.read, CARD_FRESH_S),
        asyncio.to_thread(todos.read, CARD_FRESH_S),
        return_exceptions=True,
    )
    if isinstance(calendar, BaseException):
        card["error"] = _reason(calendar, "日历这次没读到。")
        return card, ""
    tasks = [] if isinstance(todo, BaseException) else todo[0]
    card["sections"], say = today_view(now, calendar[0], tasks)
    if isinstance(todo, BaseException):
        card["sections"].append({"label": "待办", "meta": "", "rows": [], "empty": _reason(todo, "这次没读到。")})
    return card, say


async def stream_presence() -> AsyncIterator[dict[str, Any]]:
    """和对话一样的事件流：先是卡片，再是那一句。"""
    card, say = await presence_input()
    yield {"type": "agenda", **card}
    if say:
        yield {"type": "delta", "text": say}
    yield {"type": "done", "reply": say, "tools_called": []}
