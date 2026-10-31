"""日历标题说成人话：「FYP meeting with mentor」→「见导师」，「Comp30291 lecture」→「COMP30291 讲座」。

开场要快，不能现场等模型：第一次见到一个标题时在后台请模型起个短名，记在 STATE_DIR/names.json，
以后直接用；还没起好的先照原样显示。FRIDAY_NAMING=off 时不起名（测试用）。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from src.config import STATE_DIR

NAMES_PATH = STATE_DIR / "names.json"
MAX_LEN = 16
PROMPT = (
    "把下面这些日历标题改写成给中文用户看的短名，像人平时说话那样，2 到 8 个字。"
    "课程保留课程代码（如「COMP30291 讲座」「COMP34111 实验课」）；人名、地名、产品名保留原文；"
    "已经很短或没把握的就原样返回。只输出一个 JSON 对象：{原标题: 短名}。\n"
)

_lock = threading.Lock()
_cache: dict[str, str] | None = None
_pending: set[str] = set()
_worker: threading.Thread | None = None


def _load() -> dict[str, str]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(NAMES_PATH.read_text(encoding="utf-8")) if NAMES_PATH.is_file() else {}
        except (OSError, json.JSONDecodeError):
            _cache = {}
    return _cache


def short(raw: str) -> str:
    """有记下的短名就用短名；没有就照原样，并在后台去起一个。"""
    raw = (raw or "").strip()
    if not raw:
        return raw
    with _lock:
        known = _load().get(raw)
    if known:
        return known
    _queue(raw)
    return raw


def _queue(raw: str) -> None:
    global _worker
    if (os.getenv("FRIDAY_NAMING") or "").lower() in {"off", "0", "false"}:
        return
    with _lock:
        _pending.add(raw)
        if _worker and _worker.is_alive():
            return
        _worker = threading.Thread(target=_drain, daemon=True)
        _worker.start()


def _drain() -> None:
    with _lock:
        batch = sorted(_pending)
        _pending.clear()
    if not batch:
        return
    try:
        named = name_batch(batch)
    except Exception as exc:  # noqa: BLE001 — 起不了名就照原样显示，下次再试
        print(f"[WARN] naming failed: {exc}")
        return
    remember(named)


def remember(named: dict[str, Any]) -> None:
    """只收短的、非空的；起出来比原标题还长就不要。"""
    clean = {
        raw: str(name).strip()
        for raw, name in named.items()
        if isinstance(raw, str) and str(name).strip() and len(str(name).strip()) <= max(MAX_LEN, len(raw))
    }
    if not clean:
        return
    with _lock:
        cache = _load()
        cache.update(clean)
        NAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
        NAMES_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def name_batch(titles: list[str]) -> dict[str, str]:
    from src.agent import answering_model

    model, prompt = answering_model(), PROMPT + json.dumps(titles, ensure_ascii=False)
    if model.startswith("claude"):
        from src import claude

        text = claude.ask(model, prompt).strip()
    else:
        import openai

        from src.config import require_openai_api_key

        res = openai.OpenAI(api_key=require_openai_api_key()).responses.create(model=model, input=prompt)
        text = (res.output_text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1]) if start >= 0 else {}
