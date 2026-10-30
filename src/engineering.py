"""工程线（车间）：Cursor 改好了、上线了、develop 测试红了——只通过推送找他，不摆进每天的开场画面。

点开推送就是一段对话：她把改了什么给他看，要上线就照常确认（ship_pending_fix 的确认卡片）。

GitHub 的状态要 GITHUB_TOKEN（scripts/connect_github_fly.py 一次放好）；没有就只看 Cursor 这边。
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from urllib.parse import quote

from src import cursor_fix, ship
from src.config import FEEDBACK_DIR

GITHUB_API = "https://api.github.com"
CACHE_S = 60
SHIPPED_PATH = FEEDBACK_DIR / "shipped.json"

_lock = threading.Lock()
_cache: tuple[float, dict[str, Any]] | None = None


def live_sha() -> str:
    return (os.getenv("FRIDAY_GIT_SHA") or "").strip()


def _first_line(text: str, limit: int = 60) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _run_state(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not run:
        return None
    if run.get("status") != "completed":
        status = "running"
    else:
        status = "passed" if run.get("conclusion") in {"success", "skipped"} else "failed"
    commit = run.get("head_commit") or {}
    return {
        "status": status,
        "sha": run.get("head_sha") or "",
        "message": _first_line(commit.get("message") or run.get("display_title") or ""),
        "url": run.get("html_url") or "",
        "at": run.get("updated_at") or "",
    }


def github(max_age_s: float = CACHE_S) -> dict[str, Any]:
    """develop 上最新的测试和部署、开着的 PR。最多一分钟读一次 GitHub。"""
    global _cache
    if not (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")) or os.getenv("FRIDAY_GITHUB_OFFLINE"):
        return {"connected": False}
    with _lock:
        if _cache and time.monotonic() - _cache[0] <= max_age_s:
            return _cache[1]
    slug, headers = ship._repo_slug(), ship._gh_headers()
    try:
        runs = requests.get(
            f"{GITHUB_API}/repos/{slug}/actions/runs",
            headers=headers,
            params={"branch": ship._base(), "per_page": 10},
            timeout=4,
        ).json().get("workflow_runs") or []
        pulls = requests.get(
            f"{GITHUB_API}/repos/{slug}/pulls", headers=headers, params={"state": "open", "per_page": 10}, timeout=4
        ).json()
    except (requests.RequestException, ValueError, AttributeError) as exc:
        return {"connected": True, "error": str(exc)}
    state = {
        "connected": True,
        "tests": _run_state(next((r for r in runs if r.get("name") == "Tests"), None)),
        "deploy": _run_state(next((r for r in runs if r.get("name") == "Deploy Friday"), None)),
        "prs": [
            {"number": p.get("number"), "title": _first_line(p.get("title") or ""), "url": p.get("html_url") or "",
             "draft": bool(p.get("draft")), "branch": (p.get("head") or {}).get("ref") or ""}
            for p in (pulls if isinstance(pulls, list) else [])
        ],
    }
    with _lock:
        _cache = (time.monotonic(), state)
    return state


def forget() -> None:
    global _cache
    with _lock:
        _cache = None


# ---- 上线以后告诉他 ----


def record_shipped(summary: str) -> None:
    """合并成功的那一刻记一笔；新版本起来时（线上提交号变了）推一句「上线了」。"""
    SHIPPED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SHIPPED_PATH.write_text(
        json.dumps({"summary": summary, "at": datetime.now(timezone.utc).isoformat(), "live_before": live_sha()},
                   ensure_ascii=False),
        encoding="utf-8",
    )


def _shipped() -> dict[str, Any] | None:
    try:
        return json.loads(SHIPPED_PATH.read_text(encoding="utf-8")) if SHIPPED_PATH.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None


def events(now: datetime, gh: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """此刻值得推给他的工程消息（是否说过由 nudges 去重）。"""
    out: list[dict[str, Any]] = []
    job = cursor_fix.refresh_job() if cursor_fix._load_job() else None
    if job and job.get("status") in {"done", "failed", "error"}:
        agent = job.get("agent_id") or job.get("started_at") or "job"
        what = _first_line(job.get("what") or "改代码", 40)
        if job.get("status") == "done" and ship.load_pending():
            out.append({"kind": "cursor", "key": f"cursor:{agent}", "title": "Cursor 改好了",
                        "body": f"{what}。点开看改动，一键上线。", "url": f"/?n=cursor:{agent}&do=ask&what={quote('Cursor 改了什么')}", "urgency": "high"})
        elif job.get("status") != "done":
            out.append({"kind": "cursor", "key": f"cursor-failed:{agent}", "title": "Cursor 没改成",
                        "body": f"{what}：没改成。点开看看。", "url": f"/?n=cursor-failed:{agent}"})

    shipped = _shipped()
    live = live_sha()
    if shipped and live and live != shipped.get("live_before"):
        out.append({"kind": "live", "key": f"live:{live}", "title": "上线了",
                    "body": f"{_first_line(shipped.get('summary') or '刚才的改动', 50)}。刷新一下就是新的。",
                    "url": f"/?n=live:{live[:12]}"})
        SHIPPED_PATH.unlink(missing_ok=True)

    gh = gh if gh is not None else github()
    tests = gh.get("tests")
    if tests and tests["status"] == "failed":
        try:
            fresh = now.astimezone(timezone.utc) - datetime.fromisoformat(tests["at"].replace("Z", "+00:00")) < timedelta(hours=24)
        except ValueError:
            fresh = False
        if fresh:
            out.append({"kind": "ci", "key": f"ci:{tests['sha']}", "title": "develop 测试红了",
                        "body": f"{tests['message']}。点开，交给 Cursor 修。",
                        "url": f"/?n=ci:{tests['sha'][:12]}&do=ask&what={quote('develop 测试为什么红了')}"})
    return out
