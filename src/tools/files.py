"""本地文件工具：在 data/notes 下搜索与读取 Markdown。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents import function_tool

from src.config import NOTES_DIR, ROOT_DIR


def _safe_resolve(path: str) -> Path:
    """将 path 解析到 NOTES_DIR 内；禁止越界。"""
    raw = Path(path)
    if not raw.is_absolute():
        candidates = [
            ROOT_DIR / raw,
            NOTES_DIR / raw.name,
            NOTES_DIR / raw,
        ]
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                if _is_under(resolved, NOTES_DIR.resolve()) and resolved.is_file():
                    return resolved
            except OSError:
                continue
        raise FileNotFoundError(f"找不到文件: {path}")

    resolved = raw.resolve()
    if not _is_under(resolved, NOTES_DIR.resolve()):
        raise PermissionError("只能读取 data/notes/ 下的文件")
    if not resolved.is_file():
        raise FileNotFoundError(f"找不到文件: {path}")
    return resolved


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _rel_display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR)).replace("\\", "/")
    except ValueError:
        return str(path)


def search_notes(query: str) -> dict[str, Any]:
    """在本地笔记目录中按关键词搜索文件。"""
    q = (query or "").strip().lower()
    if not q:
        return {"query": query, "results": []}

    results: list[dict[str, str]] = []
    for path in sorted(NOTES_DIR.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt", ".json"}:
            continue
        text = path.read_text(encoding="utf-8")
        hay = f"{path.name}\n{_rel_display(path)}\n{text}".lower()
        tokens = [t for t in q.replace("-", " ").split() if t]
        if q not in hay and not (tokens and all(t in hay for t in tokens)):
            continue

        snippet = text.strip().replace("\n", " ")
        lower = snippet.lower()
        needle = tokens[0] if tokens else q
        idx = lower.find(needle)
        if idx >= 0:
            start = max(0, idx - 40)
            end = min(len(snippet), idx + 120)
            snippet = ("…" if start else "") + snippet[start:end] + ("…" if end < len(snippet) else "")
        else:
            snippet = snippet[:160] + ("…" if len(snippet) > 160 else "")

        title = path.stem.replace("-", " ").replace("_", " ")
        for line in text.splitlines():
            if line.startswith("#"):
                title = line.lstrip("#").strip() or title
                break

        results.append(
            {
                "path": _rel_display(path),
                "title": title,
                "snippet": snippet,
            }
        )

    return {"query": query, "results": results}


def read_note(path: str) -> dict[str, Any]:
    """读取本地笔记文件全文。"""
    resolved = _safe_resolve(path)
    return {
        "path": _rel_display(resolved),
        "content": resolved.read_text(encoding="utf-8"),
    }


@function_tool
def search_files(query: str) -> dict[str, Any]:
    """在本地笔记目录中按关键词搜索文件。

    Args:
        query: 搜索关键词（匹配文件名或正文），例如 "FYP proposal"。
    """
    return search_notes(query)


@function_tool
def read_file(path: str) -> dict[str, Any]:
    """读取本地笔记文件全文。

    Args:
        path: 文件路径，例如 data/notes/fyp-proposal.md。
    """
    return read_note(path)
