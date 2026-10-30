"""Friday 主动来找他：什么时候、说什么，全部由服务端从日历和待办算出来，不经过模型。

三种情况，宁可漏也不吵：
- 开工简报：工作日 08:30（周末 10:00）以后、中午以前，今天有安排或有要交的才发。
- 会快到了：今天要紧的会（导师、开会、截止、考试……）开始前 20 分钟到 2 小时，点开就准备要点。
- 今天截止还没划掉：下午 5 点以后。

每天最多 FRIDAY_PUSH_DAILY_MAX 条（默认 2），22:00–08:00 不打扰；同一件事只说一次。
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta
from typing import Any, Callable
from urllib.parse import quote

from src import agenda, push, todos, usage_log
from src.agenda import Timed
from src.config import effective_now
from src.presence import IMPORTANT, _clock, _spaced, _there
from src.webpush import PUSH_DIR

SENT_PATH = PUSH_DIR / "sent.jsonl"
QUIET_FROM, QUIET_UNTIL = time(22, 0), time(8, 0)
BRIEF_UNTIL = time(12, 0)
DUE_FROM = time(17, 0)
MEETING_AHEAD = (timedelta(minutes=20), timedelta(hours=2))
# 同时满足时谁先说：会快到了最要紧
PRIORITY = {"meeting": 0, "brief": 1, "due": 2}


def daily_max() -> int:
    try:
        return max(0, int(os.getenv("FRIDAY_PUSH_DAILY_MAX") or 2))
    except ValueError:
        return 2


def _morning(day: date) -> time:
    raw = os.getenv("FRIDAY_MORNING_WEEKEND" if day.weekday() >= 5 else "FRIDAY_MORNING") or (
        "10:00" if day.weekday() >= 5 else "08:30"
    )
    try:
        return time.fromisoformat(raw)
    except ValueError:
        return time(8, 30)


def quiet(moment: datetime) -> bool:
    t = moment.time()
    return t >= QUIET_FROM or t < QUIET_UNTIL


def _names(titles: list[str], limit: int = 3) -> str:
    return "、".join(titles) if len(titles) <= limit else f"{'、'.join(titles[:limit - 1])} 等 {len(titles)} 件"


def _due_today(now: datetime, tasks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    today = now.date()
    pairs = todos.ordered(tasks)
    return (
        [task["title"] for task, day in pairs if day == today],
        [task["title"] for task, day in pairs if day is not None and day < today],
    )


def _brief(now: datetime, timed: list[Timed], tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    today = now.date()
    if not (_morning(today) <= now.time() < BRIEF_UNTIL):
        return None
    left = [(s, e, ev) for s, e, ev in timed if s.date() == today and (e or s) > now]
    due, overdue = _due_today(now, tasks)
    if not left and not due and not overdue:
        return None  # 空的一天不用特意来说
    parts = []
    if left:
        shown = "，".join(f"{_clock(s)} {agenda.spoken(ev)}{_there(ev)}" for s, _, ev in left[:3])
        more = f" 等 {len(left)} 项" if len(left) > 3 else ""
        parts.append(f"今天 {len(left)} 项：{shown}{more}。")
    else:
        parts.append("今天没有安排。")
    if due:
        parts.append(f"今天截止：{_names(due)}。")
    if overdue:
        parts.append(f"已经过了截止：{_names(overdue)}。")
    key = f"brief:{today.isoformat()}"
    return {"kind": "brief", "key": key, "title": "Friday · 今天", "body": _spaced("".join(parts)), "url": f"/?n={quote(key)}"}


def _meetings(now: datetime, timed: list[Timed]) -> list[dict[str, Any]]:
    out = []
    for start, _end, event in timed:
        ahead = start - now
        if start.date() != now.date() or not (MEETING_AHEAD[0] <= ahead <= MEETING_AHEAD[1]):
            continue
        name = agenda.title(event)
        if not IMPORTANT.search(name):
            continue
        key = f"meeting:{event.get('id') or name}:{start:%Y-%m-%dT%H:%M}"
        what = agenda.spoken(event)
        out.append(
            {
                "kind": "meeting",
                "key": key,
                "title": f"{_clock(start)} {what}",
                "body": _spaced(f"{_clock(start)}：{what}{_there(event)}。点开，我把要点备好。"),
                "url": f"/?n={quote(key)}&do=prepare&what={quote(what)}",
                "urgency": "high",
            }
        )
    return out


def _due(now: datetime, tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    if now.time() < DUE_FROM:
        return None
    due, overdue = _due_today(now, tasks)
    if not due and not overdue:
        return None
    text = f"今天截止还没划掉：{_names(due)}。" if due else ""
    if overdue:
        text += f"已经过了截止：{_names(overdue)}。"
    key = f"due:{now.date().isoformat()}"
    return {"kind": "due", "key": key, "title": "Friday · 截止", "body": _spaced(text), "url": f"/?n={quote(key)}"}


def candidates(now: datetime, events: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """此刻值得来找他的事（还没去掉说过的、也没管上限），按要紧程度排。"""
    timed, _all_day = agenda.split(events)
    found = _meetings(now, timed)
    for one in (_brief(now, timed, tasks), _due(now, tasks)):
        if one:
            found.append(one)
    return sorted(found, key=lambda n: PRIORITY[n["kind"]])


# ---- 说过的 ----


def _sent() -> list[dict[str, Any]]:
    if not SENT_PATH.is_file():
        return []
    rows = []
    for line in SENT_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _mark_sent(nudge: dict[str, Any], now: datetime, delivered: int) -> None:
    SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"key": nudge["key"], "kind": nudge["kind"], "day": now.date().isoformat(), "at": now.isoformat(timespec="minutes"),
           "title": nudge["title"], "body": nudge["body"], "devices": delivered}
    with SENT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def due_now(now: datetime, events: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """此刻真要发的：不在安静时段、没说过、没超过今天的上限。"""
    if quiet(now):
        return []
    sent = _sent()
    said = {row["key"] for row in sent}
    today = sum(1 for row in sent if row.get("day") == now.date().isoformat())
    room = daily_max() - today
    if room <= 0:
        return []
    return [n for n in candidates(now, events, tasks) if n["key"] not in said][:room]


def tick(now: datetime | None = None, *, deliver: Callable[..., int] = push.deliver) -> list[dict[str, Any]]:
    """定时器每分钟叫一次：该说的就发出去。没有设备订阅时什么都不做。"""
    if not push.devices():
        return []
    now = now or effective_now()
    try:
        events = agenda.read()[0]
    except Exception as exc:  # noqa: BLE001 — 日历读不到就这一轮不说
        print(f"[WARN] nudges: calendar unavailable: {exc}")
        return []
    try:
        tasks = todos.read()[0]
    except Exception:  # noqa: BLE001
        tasks = []
    sent = []
    for nudge in due_now(now, events, tasks):
        message = {"title": nudge["title"], "body": nudge["body"], "url": nudge["url"], "tag": nudge["key"]}
        delivered = deliver(message, urgency=nudge.get("urgency", "normal"))
        if delivered:
            _mark_sent(nudge, now, delivered)
            usage_log.record("nudge", ok=True, first_token_ms=None, total_ms=0, tools=[nudge["kind"]])
            sent.append(nudge)
    return sent


def history(days: int = 7) -> list[dict[str, Any]]:
    since = (effective_now().date() - timedelta(days=days - 1)).isoformat()
    return [row for row in _sent() if row.get("day", "") >= since]
