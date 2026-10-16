"""今天到下周日的安排：读一次，开场卡片和每轮对话共用。时间是本地钟点，课表标题写成人话。"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, NamedTuple

from src.calendar_providers import get_calendar_provider
from src.calendar_providers.common import is_background_span
from src.config import effective_now
from src.context import module_names, weekday_zh

# 对话里用的日历最多旧 5 分钟；窗口被叫回时会先在后台读好
FRESH_S = 300
# 大学课表的标题形如「COMP34111/LECTURE1A/」：课程代码 / 类型加分组 / 附加信息
COURSE_CODE = re.compile(r"[A-Z]{4}\d[0-9A-Z]{4}")
KIND_NAMES = {"LABORATORY": "Lab"}

Timed = tuple[datetime, datetime | None, dict[str, Any]]


class _Snapshot(NamedTuple):
    day: date
    read_at: datetime
    taken: float
    events: list[dict[str, Any]]


_lock = threading.Lock()
_snapshot: _Snapshot | None = None


def this_sunday(today: date) -> date:
    return today + timedelta(days=6 - today.weekday())


def last_day(today: date) -> date:
    """读到下周日：问「这周」「下周」，看到的都是整周。"""
    return this_sunday(today) + timedelta(days=7)


def read(max_age_s: float = FRESH_S) -> tuple[list[dict[str, Any]], datetime]:
    """今天到下周日的事件和读到的时刻：够新就用上次的，否则现读；同一时间只读一次。"""
    global _snapshot
    with _lock:
        today = effective_now().date()
        snap = _snapshot
        if snap and snap.day == today and time.monotonic() - snap.taken <= max_age_s:
            return snap.events, snap.read_at
        days = (last_day(today) - today).days + 1
        result = get_calendar_provider().query_events(date=today.isoformat(), days=days)
        _snapshot = _Snapshot(today, effective_now(), time.monotonic(), list(result.get("events") or []))
        return _snapshot.events, _snapshot.read_at


def refresh_soon(max_age_s: float = 60) -> None:
    """在后台先读好：窗口刚被叫回，他打完字时这一轮就不用再等日历。"""
    threading.Thread(target=_read_quietly, args=(max_age_s,), daemon=True).start()


def _read_quietly(max_age_s: float) -> None:
    try:
        read(max_age_s)
    except Exception:  # noqa: BLE001
        pass


def forget() -> None:
    """日历刚被写过：下次一定现读。"""
    global _snapshot
    with _lock:
        _snapshot = None


def local_time(iso: Any) -> datetime | None:
    if not iso:
        return None
    try:
        value = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value


def day_label(day: date) -> str:
    return f"{day.month}月{day.day}日 {weekday_zh(day)}"


def when(start: datetime, end: datetime | None) -> str:
    return f"{start:%H:%M}–{end:%H:%M}" if end else f"{start:%H:%M}"


def _word(raw: str) -> str:
    raw = raw.strip()
    if raw in KIND_NAMES:
        return KIND_NAMES[raw]
    return " ".join("-".join(part.capitalize() for part in word.split("-")) for word in raw.split())


def title(event: dict[str, Any]) -> str:
    """课表标题写成人话：「COMP34111/LECTURE1A/」→「AI and Games · Lecture」。"""
    raw = str(event.get("title") or "").strip()
    parts = [part.strip() for part in raw.split("/") if part.strip()]
    if len(parts) < 2 or not COURSE_CODE.fullmatch(parts[0]):
        return raw or "（无标题）"
    code, kind, *extra = parts
    words = [_word(re.sub(r"\d+[A-Z]?$", "", kind))]
    words += [_word(part) for part in extra if re.fullmatch(r"[A-Z][A-Z -]+", part)]
    return f"{module_names().get(code, code)} · {' '.join(words)}"


def where(event: dict[str, Any]) -> str:
    """「Schuster_RUTHERFORD TH」→「Schuster Rutherford TH」；链接原样不动。"""
    place = str(event.get("location") or "").strip()
    if "://" not in place:
        place = re.sub(r"\b[A-Z]{5,}\b", lambda m: m.group().capitalize(), place.replace("_", " "))
    return place


def split(events: list[dict[str, Any]]) -> tuple[list[Timed], list[tuple[date, str]]]:
    """拆成定时事件和单日全天事件；跨多天的背景（如教学周期）不算安排。"""
    timed: list[Timed] = []
    all_day: list[tuple[date, str]] = []
    for event in events:
        if is_background_span(event):
            continue
        start = local_time(event.get("start"))
        if start is None:
            continue
        if event.get("all_day"):
            all_day.append((start.date(), title(event)))
            continue
        timed.append((start, local_time(event.get("end")), event))
    timed.sort(key=lambda item: item[0])
    return timed, all_day


def _chat_day(day: date, today: date) -> str:
    """每天的抬头把日期和星期都写死，它就不用自己推算「周一」是哪天。"""
    label = f"{day.month}月{day.day}日"
    if day == today:
        return f"今天 {label} {weekday_zh(day)}"
    if day == today + timedelta(days=1):
        return f"明天 {label} {weekday_zh(day)}"
    return f"{label} {weekday_word(day, today)}"


def weekday_word(day: date, today: date) -> str:
    """这周以外的日子说「下周X」，免得「周四」指哪一个说不清。"""
    return f"{'下' if day > this_sunday(today) else ''}{weekday_zh(day)}"


def _days(now: datetime, timed: list[Timed], all_day: list[tuple[date, str]], first: date, last: date) -> tuple[int, list[str]]:
    """一段日子：还没结束的几项，和每天一段的文字。"""
    count = 0
    lines: list[str] = []
    day = first
    while day <= last:
        rows = [f"- 全天 {name}" for d, name in all_day if d == day]
        finished = []
        for start, end, event in timed:
            if start.date() != day:
                continue
            place = where(event)
            line = f"{when(start, end)} {title(event)}{f'（{place}）' if place else ''}"
            if (end or start) <= now:
                finished.append(line)
            else:
                rows.append(f"- {line}{'（进行中）' if start <= now else ''}")
        count += len(rows)
        # 结束了的单独一行：问「还有什么」时不会把它们当成还没上的
        empty = "后面没有安排了" if finished else "没有安排"
        lines.append(f"{_chat_day(day, now.date())}：{f'{len(rows)} 项' if rows else empty}")
        lines.extend(rows)
        if finished:
            lines.append("- 已结束：" + "；".join(finished))
        day += timedelta(days=1)
    return count, lines


def chat_block() -> str:
    """每轮对话自带的日历：今天到下周日，每天一段，空的日子也写出来；每周还有几项也数好，它不用自己数。"""
    now = effective_now()
    try:
        events, read_at = read()
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).splitlines()[0] if isinstance(exc, RuntimeError) else "读取失败"
        return f"日历：这次没读到（{reason}）。问到安排时用 get_calendar_events 再试一次，还读不到就直说。"

    timed, all_day = split(events)
    today = now.date()
    sunday, monday, end = this_sunday(today), this_sunday(today) + timedelta(days=1), last_day(today)
    this_count, this_week = _days(now, timed, all_day, today, sunday)
    next_count, next_week = _days(now, timed, all_day, monday, end)
    return "\n".join(
        [
            f"日历（今天到下周日，{read_at:%H:%M} 读的）：这就是他的日历，问这些天的安排直接用，不用再查；"
            "要看备注、链接，或这些天里没有他问的事，再用 get_calendar_events 往后查。"
            "问有几项、几节，就用下面写好的数，不要自己数；同一时间的两项也是两项。",
            f"【这周，到 {sunday.month}月{sunday.day}日 周日：还有 {this_count} 项】",
            *this_week,
            f"【下周，{monday.month}月{monday.day}日–{end.month}月{end.day}日：共 {next_count} 项】",
            *next_week,
        ]
    )
