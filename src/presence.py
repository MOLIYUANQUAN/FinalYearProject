"""打开时的「今天」：服务端读真实日历，原样排成卡片；再挑出此刻最该说的一件事，模型只把它说成一句话。"""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta
from typing import Any

from src.calendar_providers import get_calendar_provider
from src.calendar_providers.common import is_background_span
from src.config import effective_now
from src.context import greeting, his_name, module_names, weekday_zh

# 今明两天都空时，往后找最近的一件
LOOKAHEAD_DAYS = 8
# 大学课表的标题形如「COMP34111/LECTURE1A/」：课程代码 / 类型加分组 / 附加信息
COURSE_CODE = re.compile(r"[A-Z]{4}\d[0-9A-Z]{4}")
KIND_NAMES = {"LABORATORY": "Lab"}
# 值得提前说的事：见导师、开会、截止、考试
IMPORTANT = re.compile(
    r"导师|会议|开会|例会|见面|截止|考试|面试|答辩|mentor|supervisor|meeting|deadline|due|exam|interview|viva",
    re.IGNORECASE,
)

Timed = tuple[datetime, datetime | None, dict[str, Any]]


def _local(iso: Any) -> datetime | None:
    if not iso:
        return None
    try:
        value = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value


def _day_label(day: date) -> str:
    return f"{day.month}月{day.day}日 {weekday_zh(day)}"


def _day_word(day: date, today: date) -> str:
    if day == today:
        return "今天"
    if day == today + timedelta(days=1):
        return "明天"
    return _day_label(day)


def _when(start: datetime, end: datetime | None) -> str:
    return f"{start:%H:%M}–{end:%H:%M}" if end else f"{start:%H:%M}"


def _span(delta: timedelta) -> str:
    hours, minutes = divmod(max(0, int(delta.total_seconds() // 60)), 60)
    if not hours:
        return f"{minutes} 分钟"
    return f"{hours} 小时" + (f" {minutes} 分钟" if minutes else "")


def _word(raw: str) -> str:
    raw = raw.strip()
    if raw in KIND_NAMES:
        return KIND_NAMES[raw]
    return " ".join("-".join(part.capitalize() for part in word.split("-")) for word in raw.split())


def _title(event: dict[str, Any]) -> str:
    """课表标题写成人话：「COMP34111/LECTURE1A/」→「AI and Games · Lecture」。"""
    raw = str(event.get("title") or "").strip()
    parts = [part.strip() for part in raw.split("/") if part.strip()]
    if len(parts) < 2 or not COURSE_CODE.fullmatch(parts[0]):
        return raw or "（无标题）"
    code, kind, *extra = parts
    words = [_word(re.sub(r"\d+[A-Z]?$", "", kind))]
    words += [_word(part) for part in extra if re.fullmatch(r"[A-Z][A-Z -]+", part)]
    return f"{module_names().get(code, code)} · {' '.join(words)}"


def _where(event: dict[str, Any]) -> str:
    """「Schuster_RUTHERFORD TH」→「Schuster Rutherford TH」；链接原样不动。"""
    place = str(event.get("location") or "").strip()
    if "://" not in place:
        place = re.sub(r"\b[A-Z]{5,}\b", lambda m: m.group().capitalize(), place.replace("_", " "))
    return place[:60]


def _at(event: dict[str, Any]) -> str:
    where = _where(event)
    return f"（{where}）" if where else ""


def _row(event: dict[str, Any], start: datetime, end: datetime | None, *, now: bool = False) -> dict[str, Any]:
    return {"time": _when(start, end), "title": _title(event), "where": _where(event), "now": now}


def _all_day_rows(titles: list[str]) -> list[dict[str, Any]]:
    return [{"time": "全天", "title": title, "where": "", "now": False} for title in titles]


def _split(events: list[dict[str, Any]]) -> tuple[list[Timed], list[tuple[date, str]]]:
    """拆成定时事件和单日全天事件；跨多天的背景（如教学周期）不算安排。"""
    timed: list[Timed] = []
    all_day: list[tuple[date, str]] = []
    for event in events:
        if is_background_span(event):
            continue
        start = _local(event.get("start"))
        if start is None:
            continue
        if event.get("all_day"):
            all_day.append((start.date(), _title(event)))
            continue
        timed.append((start, _local(event.get("end")), event))
    timed.sort(key=lambda item: item[0])
    return timed, all_day


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
                {"label": f"下一件 · {_day_label(start.date())}", "meta": "", "rows": [_row(event, start, end)], "empty": ""}
            )
        else:
            sections.append({"label": f"之后 {LOOKAHEAD_DAYS - 2} 天", "meta": "", "rows": [], "empty": "都没有安排"})
    return sections


def _focus(now: datetime, timed: list[Timed], all_day: list[tuple[date, str]]) -> str:
    """此刻最该说的一件事。挑哪件、相差多久都在这里算好，模型只负责说成一句话。"""
    today = now.date()
    tomorrow = today + timedelta(days=1)
    current = next(((s, e, ev) for s, e, ev in timed if e and s <= now < e), None)
    upcoming = [(s, e, ev) for s, e, ev in timed if s > now]
    soon = upcoming[0] if upcoming else None

    if soon is None:
        free = f"接下来 {LOOKAHEAD_DAYS - 2} 天都没有安排"
    elif soon[0].date() == today:
        free = f"现在到 {soon[0]:%H:%M} 都空着（{_span(soon[0] - now)}）"
    elif soon[0].date() == tomorrow:
        free = "今天后面都空着"
    else:
        free_days = {(today + timedelta(days=i)).weekday() for i in range((soon[0].date() - today).days)}
        head = "整个周末都空着" if {5, 6} <= free_days else "今天和明天都空着"
        free = f"{head}，一直到{weekday_zh(soon[0])} {soon[0]:%H:%M}"

    if current and soon and soon[0] - current[1] <= timedelta(minutes=15):
        gap = soon[0] - current[1]
        between = "紧接着" if gap <= timedelta(0) else f"只隔 {_span(gap)}"
        return (
            f"{_title(current[2])}还剩 {_span(current[1] - now)}，"
            f"结束后{between}就是{_title(soon[2])}{_at(soon[2])}"
        )
    if soon and soon[0].date() == today and soon[0] - now <= timedelta(hours=1):
        return f"{_title(soon[2])} {_span(soon[0] - now)}后开始{_at(soon[2])}"
    for day, title in all_day:
        if today <= day <= tomorrow and IMPORTANT.search(title):
            return f"{_day_word(day, today)}全天：{title}；{free}"
    for start, _, event in upcoming:
        if start.date() <= tomorrow and IMPORTANT.search(_title(event)):
            return f"接下来最要紧的是{_day_word(start.date(), today)} {start:%H:%M} 的{_title(event)}{_at(event)}；{free}"
    if soon and soon[0].date() == today:
        return f"{free}，之后是{_title(soon[2])}"
    if soon and soon[0].date() == tomorrow:
        return f"{free}；明天第一件是 {soon[0]:%H:%M} 的{_title(soon[2])}"
    if soon:
        return f"{free} 的{_title(soon[2])}"
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
    timed, all_day = _split(events)
    return _sections(now, timed, all_day), _focus(now, timed, all_day)


async def presence_input() -> tuple[dict[str, Any], str | None]:
    """返回（卡片，给模型的提示）：卡片立刻画出来，那句话随后流进来。日历没读到就没有那句话。"""
    now = effective_now()
    name = his_name()
    card: dict[str, Any] = {"hello": f"{greeting(now)}，{name}" if name else greeting(now), "sections": [], "error": ""}

    try:
        result = await asyncio.to_thread(
            get_calendar_provider().query_events, date=now.date().isoformat(), days=LOOKAHEAD_DAYS
        )
    except RuntimeError as exc:
        card["error"] = str(exc).splitlines()[0]
        return card, None
    except Exception:  # noqa: BLE001
        card["error"] = "日历这次没读到。"
        return card, None
    card["sections"], focus = today_view(now, list(result.get("events") or []))
    return card, _prompt(now, focus)
