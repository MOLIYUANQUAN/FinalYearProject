"""Friday 主动来找他：什么时候、说什么，全部由服务端从日历和待办算出来，不经过模型。

一天里的几个时刻，宁可漏也不吵：
- 开工：工作日 08:30（周末 10:00）以后、中午以前，今天有安排或有要交的才发。
- 会快到了：今天要紧的会（导师、开会、截止、考试……）开始前 20 分钟到 2 小时，点开就准备要点。
- 今天截止还没划掉：下午 5 点以后。
- 收工：晚上 9 点，今天替他关掉了哪几件、还有什么没做完、明天第一件和明天截止的；周日再加一句这周关掉了几件。

他亲口交代的提醒到点就发（不在这些规矩里）。每天最多 FRIDAY_PUSH_DAILY_MAX 条（默认 3），
22:00–08:00 不打扰；同一件事只说一次。
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta
from typing import Any, Callable
from urllib.parse import quote

from src import agenda, closed, conversation, engineering, push, reminders, settings, todos, usage_log
from src.agenda import Timed
from src.config import effective_now
from src.presence import IMPORTANT, _clock, _spaced, _there
from src.webpush import PUSH_DIR

SENT_PATH = PUSH_DIR / "sent.jsonl"
BRIEF_UNTIL = time(12, 0)
DUE_FROM = time(17, 0)
WRAP_FROM, WRAP_UNTIL = time(21, 0), time(22, 0)
MEETING_AHEAD = (timedelta(minutes=20), timedelta(hours=2))
# 同时满足时谁先说：会快到了最要紧
PRIORITY = {"meeting": 0, "brief": 1, "due": 2, "wrap": 3}
# 工程消息是他自己发起的事的回音（Cursor 改好了、上线了），不占每天两条的名额；
# 他刚让 Cursor 改、刚点了上线，晚上也照样告诉他。测试红了等到白天再说
ENGINEERING_ANYTIME = {"cursor", "live"}


def daily_max() -> int:
    """他在资料页里设的（没设过就是环境变量或 3）。"""
    return int(settings.get()["daily_max"])


def _morning(day: date) -> time:
    raw = os.getenv("FRIDAY_MORNING_WEEKEND" if day.weekday() >= 5 else "FRIDAY_MORNING") or (
        "10:00" if day.weekday() >= 5 else "08:30"
    )
    try:
        return time.fromisoformat(raw)
    except ValueError:
        return time(8, 30)


def quiet(moment: datetime) -> bool:
    """安静时段（资料页里能改，默认 22:00–08:00）：跨午夜的也认。"""
    current = settings.get()
    start, end, t = settings.clock(current["quiet_from"]), settings.clock(current["quiet_until"]), moment.time()
    return (t >= start or t < end) if start > end else (start <= t < end)


def _names(titles: list[str], limit: int = 3) -> str:
    return "、".join(titles) if len(titles) <= limit else f"{'、'.join(titles[:limit - 1])} 等 {len(titles)} 件"


def _due_today(now: datetime, tasks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    today = now.date()
    pairs = todos.ordered(tasks)
    return (
        [task["title"] for task, day in pairs if day == today],
        [task["title"] for task, day in pairs if day is not None and day < today and not todos.is_stale(day, today)],
    )


def _open_items(now: datetime, tasks: list[dict[str, Any]]) -> list[dict[str, str]]:
    """今天截止、刚过截止（没放太久）的待办：推送下面一件一行，「做完了 / 明天再说」点一下就办。"""
    today = now.date()
    return [
        {"key": f"task:{task['id']}", "title": task["title"]}
        for task, day in todos.ordered(tasks)
        if task.get("id") and day is not None and day <= today and not todos.is_stale(day, today)
    ][:5]


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
    return {"kind": "brief", "key": key, "title": "Friday · 今天", "body": _spaced("".join(parts)), "url": f"/?n={quote(key)}",
            "items": _open_items(now, tasks)}


def _meetings(now: datetime, timed: list[Timed]) -> list[dict[str, Any]]:
    out = []
    for start, _end, event in timed:
        ahead = start - now
        if start.date() != now.date() or not (MEETING_AHEAD[0] <= ahead <= MEETING_AHEAD[1]):
            continue
        if not IMPORTANT.search(agenda.title(event)):
            continue
        key = f"meeting:{event.get('id') or agenda.title(event)}:{start:%Y-%m-%dT%H:%M}"
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
    return {"kind": "due", "key": key, "title": "Friday · 截止", "body": _spaced(text), "url": f"/?n={quote(key)}",
            "items": _open_items(now, tasks)}


def _wrap(now: datetime, timed: list[Timed], tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """收工：关掉了什么、还差什么、明天第一件和明天截止的；周日加上这一周。什么都没有就不发。"""
    if not (WRAP_FROM <= now.time() < WRAP_UNTIL):
        return None
    today = now.date()
    tomorrow = today + timedelta(days=1)
    parts = []
    done = closed.on_day(today)
    if done:
        parts.append(f"今天替你关掉了 {len(done)} 件：{_names([r['title'] for r in done])}。")
    due, overdue = _due_today(now, tasks)
    if due or overdue:
        parts.append(f"还没做完：{_names(due + overdue)}。")
    first = next(((s, ev) for s, _, ev in timed if s.date() == tomorrow), None)
    if first:
        parts.append(f"明天第一件：{_clock(first[0])} {agenda.spoken(first[1])}{_there(first[1])}。")
    tomorrow_due = [task["title"] for task, day in todos.ordered(tasks) if day == tomorrow]
    if tomorrow_due:
        parts.append(f"明天截止：{_names(tomorrow_due)}。")
    if not parts:
        return None
    if today.weekday() == 6:
        week = closed.in_week(today)
        if week:
            parts.append(f"这周替你关掉了 {len(week)} 件。")
    key = f"wrap:{today.isoformat()}"
    return {"kind": "wrap", "key": key, "title": "Friday · 收工", "body": _spaced("".join(parts)), "url": f"/?n={quote(key)}",
            "items": _open_items(now, tasks)}


def candidates(now: datetime, events: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """此刻值得来找他的事（还没去掉说过的、也没管上限），按要紧程度排。"""
    timed, _all_day = agenda.split(events)
    found = _meetings(now, timed)
    for one in (_brief(now, timed, tasks), _due(now, tasks), _wrap(now, timed, tasks)):
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


def due_now(
    now: datetime,
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    work: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """此刻真要发的：没说过；日历和待办的不在安静时段、不超过今天的上限；工程消息另算。"""
    sent = _sent()
    said = {row["key"] for row in sent}
    out = [n for n in work or [] if n["key"] not in said and (n["kind"] in ENGINEERING_ANYTIME or not quiet(now))]
    if quiet(now):
        return out
    today = sum(1 for row in sent if row.get("day") == now.date().isoformat() and row.get("kind") in PRIORITY)
    room = daily_max() - today
    if room > 0:
        out += [n for n in candidates(now, events, tasks) if n["key"] not in said][:room]
    return out


def tick(now: datetime | None = None, *, deliver: Callable[..., int] = push.deliver) -> list[dict[str, Any]]:
    """定时器每分钟叫一次：该说的就发出去。没有设备订阅时什么都不做。"""
    if not push.devices():
        return []
    now = now or effective_now()
    # 他亲口交代的提醒先发：不看名额、不看安静时段，也不受日历读不读得到影响
    sent = _send_reminders(now, deliver)
    try:
        events = agenda.read()[0]
    except Exception as exc:  # noqa: BLE001 — 日历读不到就这一轮不说
        print(f"[WARN] nudges: calendar unavailable: {exc}")
        return sent
    try:
        tasks = todos.read()[0]
    except Exception:  # noqa: BLE001
        tasks = []
    try:
        work = engineering.events(now)
    except Exception as exc:  # noqa: BLE001 — GitHub / Cursor 读不到就这一轮不说工程的事
        print(f"[WARN] nudges: engineering unavailable: {exc}")
        work = []
    for nudge in due_now(now, events, tasks, work):
        message = {"title": nudge["title"], "body": nudge["body"], "url": nudge["url"], "tag": nudge["key"]}
        delivered = deliver(message, urgency=nudge.get("urgency", "normal"))
        if delivered:
            _mark_sent(nudge, now, delivered)
            _into_thread(nudge)
            usage_log.record("nudge", ok=True, first_token_ms=None, total_ms=0, tools=[nudge["kind"]])
            sent.append(nudge)
    return sent


def _into_thread(nudge: dict[str, Any]) -> None:
    """推送就是她发来的一条消息：也写进那条对话，点开 Friday 就在最后。她自己从 chat_block 知道说过什么。"""
    try:
        convs = conversation.store()
        cid = convs.current() or convs.latest() or convs.create()
        convs.add_message(cid, "assistant", nudge["body"], touch=False, nudge=nudge["kind"],
                          items=nudge.get("items") or [], tools=[])
    except Exception as exc:  # noqa: BLE001 — 写不进对话也不耽误推送
        print(f"[WARN] nudge not written into the conversation: {exc}")


def chat_block(now: datetime) -> str:
    """她今天主动发给他的（推送）：他可能正在回这几句。"""
    today = now.date().isoformat()
    rows = [row for row in _sent() if row.get("day") == today and row.get("body")][-6:]
    if not rows:
        return ""
    lines = "\n".join(f"- {row.get('at', '')[11:16]} {row['body']}" for row in rows)
    return f"你今天主动发给他的消息（他可能在回这些）：\n{lines}"


def _send_reminders(now: datetime, deliver: Callable[..., int]) -> list[dict[str, Any]]:
    sent = []
    for item in reminders.due(now):
        nudge = {"kind": "reminder", "key": f"reminder:{item['id']}", "title": "Friday", "body": f"{item['what']}。"}
        message = {**{k: nudge[k] for k in ("title", "body")}, "url": f"/?n={quote(nudge['key'])}", "tag": nudge["key"]}
        if deliver(message, urgency="high"):
            reminders.mark_sent(item["id"], now)
            _mark_sent(nudge, now, 1)
            _into_thread(nudge)
            usage_log.record("nudge", ok=True, first_token_ms=None, total_ms=0, tools=["reminder"])
            sent.append(nudge)
    return sent


def history(days: int = 7) -> list[dict[str, Any]]:
    since = (effective_now().date() - timedelta(days=days - 1)).isoformat()
    return [row for row in _sent() if row.get("day", "") >= since]
