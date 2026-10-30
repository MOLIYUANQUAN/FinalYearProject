"""准时提醒：「下午三点提醒我给妈妈打电话」——到点 Friday 自己来找他。

几点由服务端从他的原话算出来（不交给模型猜），存在 STATE_DIR/reminders.json；
定时器每分钟看一次，到点就推送。这是他亲口交代的事：不占每天的名额，夜里也照叫。
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from src.config import STATE_DIR
from src.todos import parse_due

REMINDERS_PATH = STATE_DIR / "reminders.json"
# 服务停了很久才回来：超过这么久的就不补发了，免得半夜收到早上的事
STALE_AFTER = timedelta(hours=6)

_lock = threading.Lock()

_CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM = r"[0-9]+|[零〇一二两三四五六七八九十]+"
_DAY_WORDS = {"今天": 0, "明天": 1, "后天": 2, "大后天": 3}
# 一个词同时说了哪天和哪个时段
_DAY_PERIOD = {"今早": (0, "早上"), "今晚": (0, "晚上"), "明早": (1, "早上"), "明晚": (1, "晚上")}
_PERIODS = ("凌晨", "早上", "早晨", "上午", "中午", "下午", "傍晚", "晚上", "夜里")
# 只说了时段没说几点
_PERIOD_DEFAULT = {"凌晨": 6, "早上": 9, "早晨": 9, "上午": 10, "中午": 12, "下午": 15, "傍晚": 18, "晚上": 20, "夜里": 22}
_AFTERNOON = {"下午", "傍晚", "晚上", "夜里"}


def _num(text: str) -> int | None:
    if text.isdigit():
        return int(text)
    text = text.replace("两", "二").replace("〇", "零").lstrip("零") or "零"
    if "十" in text:
        tens, _, ones = text.partition("十")
        if (tens and tens not in _CN) or (ones and ones not in _CN):
            return None
        return (_CN[tens] if tens else 1) * 10 + (_CN[ones] if ones else 0)
    return _CN.get(text) if len(text) == 1 else None


def _relative(text: str, now: datetime) -> datetime | None:
    """「20分钟后」「半小时后」「一个半小时以后」「两小时后」「3天后」。"""
    m = re.fullmatch(rf"(?:过)?({_NUM}|半)个?(半)?(分钟|分|小时|钟头|天)(半)?(?:后|以后|之后)", text)
    if not m:
        return None
    amount, half_a, unit, half_b = m.groups()
    n = 0.5 if amount == "半" else _num(amount)
    if n is None:
        return None
    if half_a or half_b:
        n += 0.5
    delta = {"分钟": timedelta(minutes=n), "分": timedelta(minutes=n), "天": timedelta(days=n)}.get(unit, timedelta(hours=n))
    return (now + delta).replace(second=0, microsecond=0)


def _clock(text: str) -> tuple[int, int] | None:
    """「3点」「三点半」「八点一刻」「十点零五」「15:30」→（时, 分）。"""
    m = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(rf"({_NUM})(?:点|时)(半|一刻|三刻|(?:{_NUM})分?)?", text)
    if not m:
        return None
    hour = _num(m.group(1))
    tail = m.group(2) or ""
    minute = {"半": 30, "一刻": 15, "三刻": 45, "": 0}.get(tail)
    if minute is None:
        minute = _num(tail.rstrip("分"))
    if hour is None or minute is None or hour > 24 or minute > 59:
        return None
    return hour, minute


def parse_when(said: str, now: datetime) -> datetime | None:
    """他说的时间换成本地时刻（精确到分钟）；看不懂、或者明说的那天已经过了，就是 None。"""
    text = re.sub(r"\s+", "", said or "")
    text = re.sub(r"(的时候|时候|左右|前后|整|钟)$", "", text)
    if not text:
        return None
    rel = _relative(text, now)
    if rel:
        return rel
    try:
        exact = datetime.fromisoformat(text.replace("：", ":"))
        if "T" in text or ":" in text:
            return exact.replace(tzinfo=None, second=0, microsecond=0)
    except ValueError:
        pass

    day: date | None = None
    period: str | None = None
    for word, (offset, word_period) in _DAY_PERIOD.items():
        if word in text:
            day, period = now.date() + timedelta(days=offset), word_period
            text = text.replace(word, "")
            break
    if day is None:
        for word in sorted(_DAY_WORDS, key=len, reverse=True):
            if word in text:
                day = now.date() + timedelta(days=_DAY_WORDS[word])
                text = text.replace(word, "")
                break
    if day is None:
        m = re.search(r"(?:下下|下|这|本)?(?:周|星期|礼拜)[一二三四五六日天]|(?:\d{4}年)?\d{1,2}月\d{1,2}[日号]?|\d{4}-\d{2}-\d{2}", text)
        if m:
            day = parse_due(m.group(0), now.date())
            text = text.replace(m.group(0), "")
            if day is None:
                return None
    for word in _PERIODS:
        if word in text:
            period = word
            break

    clock = _clock(text)
    explicit_day = day is not None
    if clock is None and period is None:
        if not explicit_day:
            return None
        clock = (9, 0)  # 只说了哪天：早上 9 点
    if clock is None:
        hour, minute = _PERIOD_DEFAULT[period], 0
    else:
        hour, minute = clock
        if period in _AFTERNOON and hour < 12:
            hour += 12
        elif period == "中午" and hour <= 5:
            hour += 12
    if hour == 24:
        hour = 0

    if period is None and clock is not None and hour <= 12:
        if not explicit_day:
            # 只说「3点」：今天还没过的那个 3 点（先上午、再下午）；都过了就是明天下午
            for h in (hour, hour + 12):
                if h < 24 and datetime.combine(now.date(), time(h, minute)) > now:
                    return datetime.combine(now.date(), time(h, minute))
            day = now.date() + timedelta(days=1)
        if 1 <= hour <= 6:
            hour += 12  # 「明天3点」多半是下午
    day = day or now.date()
    at = datetime.combine(day, time(hour, minute))
    if at <= now:
        if explicit_day:
            return None
        at += timedelta(days=1)  # 「下午3点」说的时候已经过了：明天
    return at


def said_when(at: datetime, now: datetime) -> str:
    """说出口的时刻：「今天下午 3 点」「明天早上 8 点半」「周五晚上 8 点」「20 分钟后（下午 3:20）」。"""
    from src.context import weekday_zh
    from src.presence import _clock

    if timedelta(0) < at - now <= timedelta(minutes=90) and at.date() == now.date():
        minutes = int((at - now).total_seconds() // 60) + (1 if (at - now).seconds % 60 else 0)
        return f"{minutes} 分钟后（{_clock(at)}）"
    days = (at.date() - now.date()).days
    head = {0: "今天", 1: "明天", 2: "后天"}.get(days)
    if head is None:
        head = f"{at.month}月{at.day}日 {weekday_zh(at)}" if days > 6 else weekday_zh(at)
    return f"{head}{_clock(at)}"


# ---- 存 ----


def _load() -> list[dict[str, Any]]:
    if not REMINDERS_PATH.is_file():
        return []
    try:
        return list(json.loads(REMINDERS_PATH.read_text(encoding="utf-8")).get("reminders") or [])
    except (OSError, json.JSONDecodeError):
        return []


def _save(items: list[dict[str, Any]]) -> None:
    REMINDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    REMINDERS_PATH.write_text(json.dumps({"reminders": items}, ensure_ascii=False, indent=2), encoding="utf-8")


def add(what: str, at: datetime) -> dict[str, Any]:
    item = {"id": f"rem-{uuid.uuid4().hex[:8]}", "what": what.strip(), "at": at.strftime("%Y-%m-%dT%H:%M"), "status": "pending"}
    with _lock:
        items = _load()
        items.append(item)
        _save(items)
    return item


def _set_status(rid: str, status: str, **extra: Any) -> dict[str, Any] | None:
    with _lock:
        items = _load()
        for item in items:
            if item["id"] == rid:
                item["status"] = status
                item.update(extra)
                _save(items)
                return item
    return None


def cancel(rid: str) -> dict[str, Any] | None:
    return _set_status(rid, "cancelled")


def restore(rid: str) -> dict[str, Any] | None:
    return _set_status(rid, "pending")


def pending() -> list[dict[str, Any]]:
    return sorted((i for i in _load() if i.get("status") == "pending"), key=lambda i: i["at"])


def due(now: datetime) -> list[dict[str, Any]]:
    """到点的；太久以前的（服务停过）直接作废，不补发。"""
    ready = []
    for item in pending():
        at = datetime.fromisoformat(item["at"])
        if at > now:
            break
        if now - at > STALE_AFTER:
            _set_status(item["id"], "missed")
            continue
        ready.append(item)
    return ready


def mark_sent(rid: str, now: datetime) -> None:
    _set_status(rid, "sent", sent_at=now.strftime("%Y-%m-%dT%H:%M"))


def find(which: str) -> list[dict[str, Any]]:
    key = re.sub(r"[\W_]+", "", which or "").casefold()
    items = pending()
    exact = [i for i in items if re.sub(r"[\W_]+", "", i["what"]).casefold() == key]
    return exact or [i for i in items if key and key in re.sub(r"[\W_]+", "", i["what"]).casefold()]


def chat_block(now: datetime) -> str:
    """每轮带给她：还没到点的提醒（时刻写好了），和怎么用提醒。"""
    items = pending()
    lines = [f"- {said_when(datetime.fromisoformat(i['at']), now)}：{i['what']}" for i in items[:10]]
    head = "他的提醒（到点服务端会推给他，你不用记）：\n" + "\n".join(lines) if lines else "他的提醒：（现在没有）"
    return head + "\n" + "\n".join(RULES)


RULES = (
    "提醒怎么用：",
    "- 他说了具体钟点或「N 分钟后」要你到时候叫他（「下午三点提醒我给妈妈打电话」「20 分钟后叫我」「明早 8 点叫我起床」）→ remind_me，"
    "when 照他的原话传，不要自己换算。只说了哪天、没有钟点的要做的事是待办（add_task），有截止日的待办我会在前一晚和当天早上自己提醒他。",
    "- 他说「不用提醒了」「取消那个提醒」→ cancel_reminder。",
    "- 回复就是工具返回的 say，一字不改；页面会给他「撤销」。",
)
