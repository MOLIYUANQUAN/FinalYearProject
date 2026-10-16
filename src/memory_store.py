"""本地薄长期记忆：JSON 事实库（非 Zep/Letta）。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.config import MEMORY_FACTS_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[dict[str, Any]]:
    if not MEMORY_FACTS_PATH.is_file():
        return []
    with MEMORY_FACTS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("facts") or [])


def _save(facts: list[dict[str, Any]]) -> None:
    MEMORY_FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FACTS_PATH.write_text(
        json.dumps({"facts": facts}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# 薄检索用的中英别名：中文问句常整段无空格，需扩成可匹配英文事实的词
_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "导师": ("mentor", "supervisor", "导师"),
    "老师": ("mentor", "supervisor", "老师"),
    "导师是谁": ("mentor", "supervisor", "导师"),
    "supervisor": ("mentor", "supervisor", "导师"),
    "mentor": ("mentor", "supervisor", "导师"),
    "偏好": ("preference", "prefer", "偏好"),
    "邮箱": ("email", "mail", "邮箱"),
    "邮件": ("email", "mail", "邮件"),
    "课表": ("timetable", "calendar", "course", "课表"),
    "日历": ("calendar", "schedule", "日历"),
    "fyp": ("fyp", "final year", "毕业设计"),
}


def _query_tokens(q: str) -> list[str]:
    """把查询拆成可匹配词：空白分词 + 中文子串 + 别名扩展。"""
    raw = (q or "").strip().lower()
    if not raw:
        return []

    tokens: list[str] = []
    for t in re.split(r"\s+", raw):
        if t:
            tokens.append(t)

    for m in re.finditer(r"[\u4e00-\u9fff]+", raw):
        run = m.group(0)
        tokens.append(run)
        if len(run) >= 2:
            for i in range(len(run) - 1):
                tokens.append(run[i : i + 2])

    for alias, expansions in _QUERY_ALIASES.items():
        if alias in raw:
            tokens.extend(expansions)

    # 保序去重
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def remember_fact(content: str, tags: str = "") -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {"ok": False, "error": "empty_content"}

    tag_list = [t.strip().lower() for t in re.split(r"[,，;；\s]+", tags) if t.strip()]
    facts = _load()
    # 简单去重：相同正文不重复添加
    for existing in facts:
        if (existing.get("content") or "").strip() == text:
            if tag_list:
                old = set(existing.get("tags") or [])
                existing["tags"] = sorted(old | set(tag_list))
                existing["updated_at"] = _now()
                _save(facts)
            return {
                "ok": True,
                "action": "updated",
                "fact": existing,
            }

    fact = {
        "id": f"mem-{uuid4().hex[:10]}",
        "content": text,
        "tags": tag_list,
        "created_at": _now(),
        "updated_at": _now(),
    }
    facts.insert(0, fact)
    _save(facts)
    return {"ok": True, "action": "created", "fact": fact}


def search_facts(query: str, top: int = 5) -> dict[str, Any]:
    q = (query or "").strip().lower()
    top = max(1, min(int(top), 20))
    facts = _load()
    if not q:
        hits = facts[:top]
    else:
        scored: list[tuple[int, str, dict[str, Any]]] = []
        tokens = _query_tokens(q)
        for fact in facts:
            blob = " ".join(
                [
                    str(fact.get("content") or ""),
                    " ".join(fact.get("tags") or []),
                ]
            ).lower()
            score = sum(1 for t in tokens if t in blob)
            if q in blob:
                score = max(score, 1)
            if score > 0:
                scored.append((score, fact.get("updated_at") or "", fact))
        # 分高优先；同分取最近更新
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        hits = [f for _, _, f in scored[:top]]

    return {
        "ok": True,
        "query": query,
        "count": len(hits),
        "facts": hits,
    }


def forget_fact(fact_id: str) -> dict[str, Any]:
    fid = (fact_id or "").strip()
    facts = _load()
    kept = [f for f in facts if f.get("id") != fid]
    if len(kept) == len(facts):
        return {"ok": False, "error": "not_found", "id": fid}
    _save(kept)
    return {"ok": True, "action": "deleted", "id": fid}
