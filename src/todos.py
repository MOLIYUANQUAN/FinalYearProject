"""待办：读一次，开场卡片和每轮对话共用。「周四」「下周一」是哪天由这里算，模型不用自己推算。"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, NamedTuple

from src.agenda import this_sunday, weekday_word
from src.config import effective_now, get_tasks_backend
from src.context import weekday_zh
from src.tasks_providers import get_tasks_provider

FRESH_S = 300
SOURCE_NAMES = {"google": "Google Tasks", "mock": "演示待办"}
RELATIVE_DAYS = {"今天": 0, "今晚": 0, "明天": 1, "明晚": 1, "后天": 2, "大后天": 3}
WEEKDAY_INDEX = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


class _Snapshot(NamedTuple):
    day: date
    read_at: datetime
    taken: float
    tasks: list[dict[str, Any]]


_lock = threading.Lock()
_snapshot: _Snapshot | None = None


def connected() -> bool:
    try:
        return get_tasks_backend() != "none"
    except RuntimeError:
        return False


def read(max_age_s: float = FRESH_S) -> tuple[list[dict[str, Any]], datetime]:
    """没做完的待办和读到的时刻：够新就用上次的，否则现读；没接入时是空的。"""
    global _snapshot
    with _lock:
        today = effective_now().date()
        snap = _snapshot
        if snap and snap.day == today and time.monotonic() - snap.taken <= max_age_s:
            return snap.tasks, snap.read_at
        provider = get_tasks_provider()
        tasks = provider.list_open() if provider else []
        _snapshot = _Snapshot(today, effective_now(), time.monotonic(), tasks)
        return tasks, _snapshot.read_at


def forget() -> None:
    """待办刚被改过：下次一定现读。"""
    global _snapshot
    with _lock:
        _snapshot = None


def parse_due(said: str, today: date) -> date | None:
    """他说的日子换成日期：「今天」「周四」「下周一」「10月22日」「2026-10-22」；看不懂就是 None。"""
    text = re.sub(r"\s+", "", said or "")
    text = re.sub(r"(之前|以前|前|交|截止|到期)$", "", text)
    text = re.sub(r"(早上|上午|中午|下午|傍晚|晚上|凌晨)?(\d{1,2}([:：]\d{2}|点半?))?$", "", text)
    if text in RELATIVE_DAYS:
        return today + timedelta(days=RELATIVE_DAYS[text])
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    week = re.fullmatch(r"(下下|下|这|本)?(?:周|星期|礼拜)([一二三四五六日天])", text)
    if week:
        prefix, index = week.group(1), WEEKDAY_INDEX[week.group(2)]
        monday = today - timedelta(days=today.weekday())
        if prefix in ("这", "本"):
            return monday + timedelta(days=index)
        if prefix:
            return monday + timedelta(days=(14 if prefix == "下下" else 7) + index)
        # 只说「周四」：从今天算起最近的那个周四
        return today + timedelta(days=(index - today.weekday()) % 7)

    month_day = re.fullmatch(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]?", text) or re.fullmatch(
        r"()(\d{1,2})/(\d{1,2})", text
    )
    if not month_day:
        return None
    year = int(month_day.group(1)) if month_day.group(1) else today.year
    try:
        day = date(year, int(month_day.group(2)), int(month_day.group(3)))
    except ValueError:
        return None
    if not month_day.group(1) and day < today - timedelta(days=60):
        day = day.replace(year=year + 1)
    return day


# 过了截止好几天还挂着的：多半早办完了或者不要了。不再顶到「现在」、不再推送，只在时间线上安静地问一句
STALE_AFTER_DAYS = 2


def is_stale(due: date | None, today: date) -> bool:
    return due is not None and (today - due).days > STALE_AFTER_DAYS


def due_date(task: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(task.get("due") or ""))
    except ValueError:
        return None


def when_due(due: date, today: date) -> str:
    """截止日说成「今天 10月16日」「周四 10月22日」「下周二 10月27日」；过了的说过了几天。"""
    label = f"{due.month}月{due.day}日"
    if due < today:
        return f"{label} {weekday_zh(due)}，已过 {(today - due).days} 天"
    if due == today:
        return f"今天 {label}"
    if due == today + timedelta(days=1):
        return f"明天 {label}"
    if due <= this_sunday(today) + timedelta(days=7):
        return f"{weekday_word(due, today)} {label}"
    return f"{label} {weekday_zh(due)}"


def ordered(tasks: list[dict[str, Any]]) -> list[tuple[dict[str, Any], date | None]]:
    """按截止日排，没写截止的放最后。"""
    pairs = [(task, due_date(task)) for task in tasks]
    return sorted(pairs, key=lambda pair: (pair[1] is None, pair[1] or date.max))


def chat_block() -> str:
    """每轮对话自带的待办：没做完的都在，截止日写成「周四 10月22日」，几件也数好。没接入就什么都不写。"""
    if not connected():
        return ""
    today = effective_now().date()
    try:
        tasks, read_at = read()
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).splitlines()[0] if isinstance(exc, RuntimeError) else "读取失败"
        return f"待办：这次没读到（{reason}）。他交代要做的事时直说待办现在连不上，不要说记下了。"

    pairs = ordered(tasks)
    overdue = sum(1 for _, due in pairs if due and due < today)
    due_today = sum(1 for _, due in pairs if due == today)
    counts = f"没做完的 {len(pairs)} 件" + (f"，今天截止 {due_today} 件" if due_today else "")
    counts += f"，过了截止 {overdue} 件" if overdue else ""
    lines = [f"- {task['title']}：{f'截止 {when_due(due, today)}' if due else '没写截止'}" for task, due in pairs]
    return "\n".join(
        [
            f"待办（{SOURCE_NAMES.get(get_tasks_backend(), '待办')}，{read_at:%H:%M} 读的）：{counts}。",
            *(lines or ["（清单是空的）"]),
            "待办怎么用：",
            *TASK_RULES,
        ]
    )


TASK_RULES = (
    "- 他问「还有几件没做」「有什么待办」「要交什么」，问的就是上面这份：直接用它答，不调用工具；几件就用写好的数。",
    "- 他交代要做完的事（「Lab 3 周四交」「记得买牛奶」「明天给妈妈打电话」）是待办，不是记忆："
    "直接 add_task，不用先问，也不用 remember_fact；没说日子就不带日子。说了具体钟点、要你到点叫他的是提醒（remind_me）。",
    "- 上面清单里已经有的，他再说一次也照样 add_task：工具会回「已经记着了」，不会记重。",
    "- 他改口刚交代的截止日（「说错了，是周五」）→ 再 add_task 一次，同一个名字、新的日子，工具会把日子改过来。",
    "- 他说哪件做完了 → complete_task。",
    "- 回复就是 add_task / complete_task 返回的 say，一字不改，不加别的；调用了几次就几行。页面会给他「撤销」。",
    "- 约了人、有具体钟点或地点的（「明天下午三点和 Tom 喝咖啡」）是日程，不是待办：直接 create_calendar_event，页面会给他「撤销」。",
)


def undo(items: list[dict[str, Any]]) -> None:
    """他点了「撤销」：刚记下的删掉，刚划掉的恢复，刚改的日子改回去。后做的先撤。"""
    provider = get_tasks_provider()
    if provider is None:
        raise RuntimeError("待办还没接入。")
    try:
        for item in reversed(items):
            if item["kind"] == "task_added":
                provider.delete(item["id"])
            elif item["kind"] == "task_completed":
                provider.reopen(item["id"])
            elif item["kind"] == "task_due_changed":
                provider.set_due(item["id"], due_date(item))
    finally:
        forget()
