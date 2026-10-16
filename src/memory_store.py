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
        tokens = [t for t in re.split(r"\s+", q) if t]
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
