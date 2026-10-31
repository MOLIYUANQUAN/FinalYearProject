"""对话存在服务端：手机上聊一半，电脑上接着聊；页面刷新、换设备都不丢。

两样东西放在同一个 SQLite 文件里（`STATE_DIR/conversations.db`）：
- 给模型看的：Agents SDK 的 SQLiteSession，含工具调用和结果（「回刚才那封」不用再搜）。
- 给页面看的：每条消息的文字、开场卡片、工具、撤销、待确认。

页面上只有一条对话（thread：最近两周、按时间连着）。给模型的会话仍按「同一天、两小时内」分段，
免得上下文无限长；新的一段会先带上前一段最后几句（carry_over）。一天里一直聊、一段长到 ROLL_AT，
也悄悄换一段（他看到的还是同一条）。
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agents import SQLiteSession

from src.config import CONVERSATIONS_DB

IDLE_S = 2 * 60 * 60
THREAD_DAYS = 14
THREAD_MAX = 200
CARRY_LINES = 6
CARRY_WITHIN_S = 24 * 60 * 60
# 给模型的一段最长多少 token（上一次问模型时的输入加输出）。Claude 能看 1M，备用的 GPT-5 只能 272K；
# 这里远在两者之下换段，也免得每句话都把很长的历史再付一遍钱
ROLL_AT = 150_000
FULL = 10**9  # 模型说「太长了」：记成满的，下一句就换段
# 能贴在气泡上的表情（和 WhatsApp 默认的一样）
REACTIONS = ("👍", "❤️", "😂", "😮", "😢", "🙏")


def reaction_of(text: str) -> str | None:
    """她整条回复只有一个表情：那就是贴在他那条消息上的，不是一句话。"""
    said = (text or "").strip().replace("\ufe0f", "")
    return next((r for r in REACTIONS if said == r.replace("\ufe0f", "")), None)


def split_reaction(text: str) -> tuple[str | None, str]:
    """她回复的第一行只有一个表情：那是贴在他那条消息上的；剩下的才是她要说的话。"""
    first, _, rest = (text or "").strip().partition("\n")
    emoji = reaction_of(first)
    return (emoji, rest.strip()) if emoji else (None, text)


def paragraphs(text: str) -> list[str]:
    """和页面一样分段：一段一个气泡。"""
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


class Conversations:
    def __init__(self, db_path: str | Path = CONVERSATIONS_DB) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    started_at REAL NOT NULL,
                    last_active_at REAL NOT NULL,
                    context_tokens INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}',
                    at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_messages
                    ON conversation_messages (conversation_id, id);
                """
            )
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(conversations)")}
            if "context_tokens" not in columns:  # 之前建的库
                self._conn.execute("ALTER TABLE conversations ADD COLUMN context_tokens INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()
        self._sessions: dict[str, SQLiteSession] = {}

    # ---- 对话 ----

    def create(self) -> str:
        cid = uuid.uuid4().hex[:16]
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversations (id, started_at, last_active_at) VALUES (?, ?, ?)", (cid, now, now)
            )
            self._conn.commit()
        return cid

    def exists(self, cid: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM conversations WHERE id = ?", (cid,)).fetchone()
        return row is not None

    def current(self, now: float | None = None) -> str | None:
        """最近一次对话；放太久了（换了一天，或两小时没说话）就算结束了。"""
        now = time.time() if now is None else now
        with self._lock:
            row = self._conn.execute(
                "SELECT id, started_at, last_active_at FROM conversations ORDER BY last_active_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        same_day = datetime.fromtimestamp(row["started_at"]).date() == datetime.fromtimestamp(now).date()
        if not same_day or now - row["last_active_at"] > IDLE_S:
            return None
        return row["id"]

    def latest(self) -> str | None:
        """最近说过话的那一段（不管是不是已经放久了）。"""
        with self._lock:
            row = self._conn.execute("SELECT id FROM conversations ORDER BY last_active_at DESC LIMIT 1").fetchone()
        return row["id"] if row else None

    def size(self, cid: str) -> int:
        """这一段给模型的有多长（token）。"""
        with self._lock:
            row = self._conn.execute("SELECT context_tokens FROM conversations WHERE id = ?", (cid,)).fetchone()
        return int(row["context_tokens"]) if row else 0

    def set_size(self, cid: str, tokens: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE conversations SET context_tokens = ? WHERE id = ?", (int(tokens), cid))
            self._conn.commit()

    def touch(self, cid: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE conversations SET last_active_at = ? WHERE id = ?", (time.time(), cid))
            self._conn.commit()

    # ---- 页面上的消息 ----

    def add_message(self, cid: str, role: str, content: str, *, touch: bool = True, **data: Any) -> int:
        """touch=False：推送这类她自己发的，不把一段放久了的对话算作「刚聊过」。"""
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO conversation_messages (conversation_id, role, content, data, at) VALUES (?, ?, ?, ?, ?)",
                (cid, role, content, json.dumps(data, ensure_ascii=False), now),
            )
            if touch:
                self._conn.execute("UPDATE conversations SET last_active_at = ? WHERE id = ?", (now, cid))
            self._conn.commit()
            return int(cur.lastrowid)

    def update_message(self, message_id: int, *, content: str | None = None, **data: Any) -> None:
        with self._lock:
            row = self._conn.execute("SELECT content, data FROM conversation_messages WHERE id = ?", (message_id,)).fetchone()
            if row is None:
                return
            merged = {**json.loads(row["data"] or "{}"), **data}
            self._conn.execute(
                "UPDATE conversation_messages SET content = ?, data = ? WHERE id = ?",
                (row["content"] if content is None else content, json.dumps(merged, ensure_ascii=False), message_id),
            )
            self._conn.commit()

    def message(self, message_id: int) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT id, conversation_id, role, content, data, at FROM conversation_messages WHERE id = ?", (message_id,)
            ).fetchone()
        if r is None:
            return None
        return {"id": r["id"], "conversation_id": r["conversation_id"], "role": r["role"], "content": r["content"],
                "at": int(r["at"] * 1000), **json.loads(r["data"] or "{}")}

    def last_hers(self, before: int) -> dict[str, Any] | None:
        """在这条消息之前，她最后说的那一条（整条对话里，不分段）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM conversation_messages WHERE role != 'user' AND id < ? ORDER BY id DESC LIMIT 1", (before,)
            ).fetchone()
        return self.message(row["id"]) if row else None

    def recent_reactions(self, since: float) -> list[tuple[str, str]]:
        """他最近贴在她话上的表情：(那一段话, 表情)。"""
        out = []
        for m in self.thread()[-60:]:
            if m["role"] == "user" or (m.get("reacted_at") or 0) < since:
                continue
            parts = paragraphs(m["content"])
            for part, emoji in (m.get("reactions") or {}).items():
                index = int(part) if str(part).isdigit() else 0
                if index < len(parts):
                    out.append((parts[index], emoji))
        return out

    def messages(self, cid: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, role, content, data, at FROM conversation_messages WHERE conversation_id = ? ORDER BY id",
                (cid,),
            ).fetchall()
        return [
            {"id": r["id"], "role": r["role"], "content": r["content"], "at": int(r["at"] * 1000), **json.loads(r["data"] or "{}")}
            for r in rows
        ]

    def thread(self, now: float | None = None) -> list[dict[str, Any]]:
        """页面上的那一条对话：最近两周的消息按时间连起来。没聊就又开了一次场的，只留后一次。"""
        since = (time.time() if now is None else now) - THREAD_DAYS * 24 * 60 * 60
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, conversation_id, role, content, data, at FROM conversation_messages "
                "WHERE at >= ? ORDER BY at DESC, id DESC LIMIT ?",
                (since, THREAD_MAX),
            ).fetchall()
        messages = [
            {"id": r["id"], "conversation_id": r["conversation_id"], "role": r["role"], "content": r["content"],
             "at": int(r["at"] * 1000), **json.loads(r["data"] or "{}")}
            for r in reversed(rows)
        ]
        return [m for i, m in enumerate(messages) if not (m.get("agenda") is not None and i + 1 < len(messages)
                                                          and messages[i + 1].get("agenda") is not None)]

    def carry_over(self, cid: str, now: float | None = None) -> list[dict[str, str]]:
        """新的一段要带上的：前一段（一天以内的）最后几句话，只要文字。"""
        now = time.time() if now is None else now
        with self._lock:
            prev = self._conn.execute(
                "SELECT id FROM conversations WHERE id != ? AND last_active_at >= ? ORDER BY last_active_at DESC LIMIT 1",
                (cid, now - CARRY_WITHIN_S),
            ).fetchone()
            if prev is None:
                return []
            rows = self._conn.execute(
                "SELECT role, content FROM conversation_messages WHERE conversation_id = ? AND content != '' "
                "ORDER BY id DESC LIMIT ?",
                (prev["id"], CARRY_LINES),
            ).fetchall()
        return [{"role": "user" if r["role"] == "user" else "assistant", "content": r["content"]} for r in reversed(rows)]

    def close(self) -> None:
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
        with self._lock:
            self._conn.close()

    # ---- 给模型看的 ----

    def session(self, cid: str) -> SQLiteSession:
        if cid not in self._sessions:
            self._sessions[cid] = SQLiteSession(cid, db_path=self.db_path if self.db_path != ":memory:" else ":memory:")
        return self._sessions[cid]


_default: Conversations | None = None


def store() -> Conversations:
    global _default
    if _default is None:
        _default = Conversations()
    return _default
