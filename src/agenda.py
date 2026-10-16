"""今天起几天的安排：读一次，开场卡片和每轮对话共用。时间是本地钟点，课表标题写成人话。"""

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

LOOKAHEAD_DAYS = 8
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


def read(max_age_s: float = FRESH_S) -> tuple[list[dict[str, Any]], datetime]:
    """今天起 LOOKAHEAD_DAYS 天的事件和读到的时刻：够新就用上次的，否则现读；同一时间只读一次。"""
    global _snapshot
    with _lock:
        today = effective_now().date()
        snap = _snapshot
        if snap and snap.day == today and time.monotonic() - snap.taken <= max_age_s:
            return snap.events, snap.read_at
        result = get_calendar_provider().query_events(date=today.isoformat(), days=LOOKAHEAD_DAYS)
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
    this_sunday = today + timedelta(days=6 - today.weekday())
    return f"{label} {'下' if day > this_sunday else ''}{weekday_zh(day)}"


def chat_block() -> str:
    """每轮对话自带的日历：今天起每天一段，空的日子也写出来，免得它去猜。"""
    now = effective_now()
    try:
        events, read_at = read()
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).splitlines()[0] if isinstance(exc, RuntimeError) else "读取失败"
        return f"日历：这次没读到（{reason}）。问到安排时用 get_calendar_events 再试一次，还读不到就直说。"

    timed, all_day = split(events)
    lines = [
        f"日历（今天起 {LOOKAHEAD_DAYS} 天，{read_at:%H:%M} 读的）：这就是他的日历，"
        "问这几天的安排直接用，不用再查；要看备注、链接或更远的日子，再用 get_calendar_events。"
    ]
    for offset in range(LOOKAHEAD_DAYS):
        day = now.date() + timedelta(days=offset)
        rows = [f"- 全天 {name}" for d, name in all_day if d == day]
        for start, end, event in timed:
            if start.date() != day:
                continue
            place = where(event)
            state = "（已结束）" if (end or start) <= now else "（进行中）" if start <= now else ""
            rows.append(f"- {when(start, end)} {title(event)}{f'（{place}）' if place else ''}{state}")
        lines.append(f"{_chat_day(day, now.date())}：{'' if rows else '没有安排'}")
        lines.extend(rows)
    return "\n".join(lines)
