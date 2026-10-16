"""打开时的第一句话：服务端直接读接下来几天的真实日历，模型只负责把它说成人话。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

from src.calendar_providers import get_calendar_provider
from src.calendar_providers.common import is_background_span
from src.config import effective_now
from src.context import greeting, weekday_zh

# 今明两天都空时，往后找最近的一件
LOOKAHEAD_DAYS = 8

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


def _describe(event: dict[str, Any], start: datetime, end: datetime | None) -> str:
    when = f"{start:%H:%M}–{end:%H:%M}" if end else f"{start:%H:%M}"
    line = f"{when} {event.get('title') or '（无标题）'}"
    location = str(event.get("location") or "").strip()
    if location:
        line += f"（{location[:60]}）"
    return line


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
            all_day.append((start.date(), str(event.get("title") or "（无标题）")))
            continue
        timed.append((start, _local(event.get("end")), event))
    timed.sort(key=lambda item: item[0])
    return timed, all_day


def _calendar_lines(now: datetime, events: list[dict[str, Any]]) -> list[str]:
    today = now.date()
    tomorrow = today + timedelta(days=1)
    timed, all_day = _split(events)

    remaining: list[str] = []
    finished = 0
    for start, end, event in timed:
        if start.date() != today:
            continue
        if (end or start) <= now:
            finished += 1
            continue
        line = "· " + _describe(event, start, end)
        if start <= now:
            line += " ← 进行中"
        remaining.append(line)
    tomorrow_lines = ["· " + _describe(e, s, en) for s, en, e in timed if s.date() == tomorrow]

    lines = ["【今天还剩】", *(remaining or ["无"])]
    if finished:
        lines.append(f"【今天已结束】{finished} 项")
    today_all_day = [title for day, title in all_day if day == today]
    if today_all_day:
        lines.append("【今天全天】" + "；".join(today_all_day))
    lines.append(f"【明天 {_day_label(tomorrow)}】")
    lines += tomorrow_lines or ["无"]
    tomorrow_all_day = [title for day, title in all_day if day == tomorrow]
    if tomorrow_all_day:
        lines.append("【明天全天】" + "；".join(tomorrow_all_day))

    if not remaining and not tomorrow_lines:
        later = next((item for item in timed if item[0].date() > tomorrow), None)
        if later:
            start, end, event = later
            lines.append(f"【之后最近的一件】{_day_label(start.date())} {_describe(event, start, end)}")
        else:
            lines.append(f"【之后 {LOOKAHEAD_DAYS - 2} 天】都没有安排")
    return lines


async def presence_input() -> str:
    now = effective_now()
    today = now.date()
    provider = get_calendar_provider()

    try:
        result = await asyncio.to_thread(
            provider.query_events, date=today.isoformat(), days=LOOKAHEAD_DAYS
        )
    except Exception as exc:  # noqa: BLE001
        calendar = [f"【日历】这次没读到（{str(exc)[:160]}）。如实说日历暂时读不到，别猜。"]
    else:
        calendar = _calendar_lines(now, list(result.get("events") or []))

    hello = greeting(now)
    return "\n".join(
        [
            "【他刚打开你。下面的日历是刚从他的真实日历读到的。】",
            f"【此刻】{today.isoformat()} {weekday_zh(today)} {now:%H:%M}",
            *calendar,
            "",
            "写你开口的第一句话：",
            f"- 第一行：{hello}，叫他的名字。",
            "- 接着一到三行：现在最该知道的事。今天还有安排，就说还剩什么、下一件是什么；"
            "今天没有了，就说明天的第一件事；明天也空着，就说之后最近的一件。",
            "- 只有具体依据时才加一行建议（比如两件事之间空档很短、下一件得提前出发或准备）；"
            "没有就不写，不说空话。",
            "- 只用上面的日历数据，不补充任何没给出的事件。不要问问题，不用 Markdown，不复述他的档案。",
        ]
    )
