"""「绝不没经过你就动手」的硬约束：写操作在代码里停下，等他点确认才执行。

以前靠模型自己传 user_confirmed=True，模型想跳过就能跳过；现在用 Agents SDK 的
needs_approval：工具调用到这里就暂停，服务端把要做的事原样写给他看，他说「确认」才继续。
确认的永远是那一个具体动作（收件人、正文、时间都定了），不是靠关键词猜他在确认什么。
"""

from __future__ import annotations

import re
from typing import Any

from src import ship

# 他回这些就算同意 / 不同意（去掉标点和空白后整句匹配；别的话一律当作换了话题，不执行）
_YES = {
    "确认", "确定", "同意", "好", "好的", "好啊", "可以", "行", "嗯", "对", "是", "发吧", "发", "发送",
    "建吧", "创建", "创建吧", "确认创建", "确认发送", "部署", "部署吧", "确认部署", "上线", "删吧", "删", "改吧",
    "开工", "去吧", "执行", "忘掉", "忘了吧", "交给它", "ok", "okay", "yes", "y", "sure", "go", "do it", "confirm",
}
_NO = re.compile(r"^(取消|不要|不用|别|算了|先不|不发|不建|不删|不部署|留着|停|no\b|nope|cancel|don'?t)", re.IGNORECASE)
_PUNCT = re.compile(r"[\s。，、！？!?,.~～…：:；;「」\"'（）()]+")


def decide(message: str) -> str:
    """他对待确认操作的回复 → approve / reject / other。"""
    text = _PUNCT.sub(" ", message or "").strip().lower()
    if not text:
        return "other"
    if _NO.match(text):
        return "reject"
    if text in _YES or text.replace(" ", "") in _YES:
        return "approve"
    return "other"


async def mail_change_needs_approval(_ctx: Any, params: dict[str, Any], _call_id: str) -> bool:
    """标已读 / 未读直接做；归档、扔垃圾桶先问。"""
    return params.get("action") in {"archive", "trash"}


def _clip(text: str, limit: int = 600) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def describe(name: str, args: dict[str, Any]) -> str:
    """把待确认的那一步原样写给他看。全部由服务端拼，不经过模型。"""
    if name == "send_email":
        lines = [f"发邮件给 {args.get('to', '')}"]
        if args.get("cc"):
            lines.append(f"抄送 {args['cc']}")
        lines.append(f"主题：{args.get('subject', '')}")
        lines.append("")
        lines.append(_clip(args.get("body", "")))
        return "\n".join(lines)
    if name == "create_calendar_event":
        when = f"{str(args.get('start', '')).replace('T', ' ')} – {str(args.get('end', '')).replace('T', ' ')[-5:]}"
        text = f"在日历里加「{args.get('title', '')}」：{when}"
        if args.get("location"):
            text += f"，{args['location']}"
        if args.get("notes"):
            text += f"\n备注：{_clip(args['notes'], 200)}"
        return text
    if name == "modify_email":
        verb = {"archive": "归档", "trash": "扔进垃圾桶"}.get(str(args.get("action")), str(args.get("action")))
        return f"把这封邮件{verb}（{args.get('message_id', '')}）"
    if name == "forget_fact":
        return f"忘掉这条记忆：{args.get('fact_id', '')}"
    if name == "fix_friction_with_cursor":
        what = args.get("what") or args.get("friction_id") or "改代码"
        return f"让 Cursor 改 Friday 的仓库：{what}"
    if name == "ship_pending_fix":
        pending = ship.load_pending()
        preview = ship.preview_text(pending) if pending else "（没找到待部署的改动）"
        return f"合进 develop 并部署到云上。\n{preview}"
    shown = "，".join(f"{k}={v}" for k, v in args.items() if v not in (None, ""))
    return f"{name}（{shown}）"


# 她问的那一句和页面上的两个按钮是一对（按钮上的字就是他的回答，decide 认得）
QUESTIONS = {
    "send_email": "发吗？",
    "modify_email": "这样办吗？",
    "forget_fact": "忘掉吗？",
    "fix_friction_with_cursor": "交给 Cursor 吗？",
    "ship_pending_fix": "上线吗？",
}


def prompt(approvals: list[dict[str, Any]]) -> str:
    """待确认时她给他看的那段：要做的事原样写出来，最后问一句。"""
    body = "\n\n".join(describe(a["name"], a.get("arguments") or {}) for a in approvals)
    names = {a["name"] for a in approvals}
    question = QUESTIONS.get(next(iter(names)), "这样办吗？") if len(names) == 1 else "这样办吗？"
    return f"{body}\n\n{question}"
