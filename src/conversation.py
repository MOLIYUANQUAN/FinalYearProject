"""对话存在服务端：手机上聊一半，电脑上接着聊；页面刷新、换设备都不丢。

两样东西放在同一个 SQLite 文件里（`STATE_DIR/conversations.db`）：
- 给模型看的：Agents SDK 的 SQLiteSession，含工具调用和结果（「回刚才那封」不用再搜）。
- 给页面看的：每条消息的文字、开场卡片、工具、撤销、待确认。

页面上只有一条对话（thread：最近两周、按时间连着）。给模型的会话仍按「同一天、两小时内」分段，
免得上下文无限长；新的一段会先带上前一段最后几句（carry_over）。
"""

from __future__ import annotations

import json
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
                    last_active_at REAL NOT NULL
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

    def touch(self, cid: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE conversations SET last_active_at = ? WHERE id = ?", (time.time(), cid))
            self._conn.commit()

    # ---- 页面上的消息 ----

    def add_message(self, cid: str, role: str, content: str, **data: Any) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO conversation_messages (conversation_id, role, content, data, at) VALUES (?, ?, ?, ?, ?)",
                (cid, role, content, json.dumps(data, ensure_ascii=False), now),
            )
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
