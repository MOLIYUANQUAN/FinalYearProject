"""用 Cursor Cloud Agents API 按一条产品摩擦改仓库。

Windows 上 cursor-sdk 的本机 bridge 会踩 WinError 10038，所以默认走
https://api.cursor.com/v1/agents（纯 HTTP），不依赖本机 bridge。
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from src import friction
from src.config import load_env

DEFAULT_REPO = "https://github.com/MOLIYUANQUAN/FinalYearProject"
DEFAULT_REF = "develop"
DEFAULT_MODEL = "composer-2.5"
API = "https://api.cursor.com/v1"
POLL_S = 5
# 云上改代码可能要十几分钟
TIMEOUT_S = 20 * 60


def _api_key() -> str:
    load_env()
    return (os.getenv("CURSOR_API_KEY") or "").strip()


def _repo_url() -> str:
    return (os.getenv("CURSOR_REPO_URL") or DEFAULT_REPO).strip() or DEFAULT_REPO


def _repo_ref() -> str:
    return (os.getenv("CURSOR_REPO_REF") or DEFAULT_REF).strip() or DEFAULT_REF


def _model() -> str:
    return (os.getenv("CURSOR_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _prompt_for(item: dict[str, Any]) -> str:
    better = (item.get("better") or "").strip()
    better_line = f"\n他希望：{better}" if better else ""
    return f"""你在 Jimmy 的 FYP 仓库里改 Friday 产品代码。

产品摩擦（必须消掉）：
{item.get("what")}{better_line}

约束：
- 只做消掉这条摩擦所需的最小改动；别顺手重构。
- 以 develop 为起点；别动 .env、secrets、token。
- 注释和用户可见文案用中文，跟现有风格一致。
- 「需要你」是稀缺打扰面：明天的日历项不要进 attention；标题里已过点的待办不要再催。
- 改完用几句话说明改了哪些文件、如何验收。
"""


def _error_body(res: requests.Response) -> str:
    try:
        data = res.json()
        return str(data.get("message") or data.get("error") or data)[:300]
    except Exception:  # noqa: BLE001
        return (res.text or f"HTTP {res.status_code}")[:300]


def run_fix(friction_id: str) -> dict[str, Any]:
    """按 friction id 起一次云上 Cursor Agent，轮询到结束。"""
    key = _api_key()
    if not key:
        return {
            "ok": False,
            "error": "missing_cursor_api_key",
            "message": (
                "还没有 CURSOR_API_KEY。到 https://cursor.com/dashboard/integrations 创建一把，"
                "写进本机 .env，云上再跑一次 deploy_fly.py。"
            ),
        }

    fid = (friction_id or "").strip()
    item = next((x for x in friction.open_items(50) if x.get("id") == fid), None)
    if item is None:
        return {"ok": False, "error": "not_found", "message": "没有这条未改的摩擦。先 list_friction 看 id。"}

    payload = {
        "prompt": {"text": _prompt_for(item)},
        "model": {"id": _model()},
        "repos": [{"url": _repo_url(), "startingRef": _repo_ref()}],
        "autoCreatePR": True,
        "skipReviewerRequest": True,
        "name": f"friday-friction-{fid[:8]}",
    }
    try:
        created = requests.post(f"{API}/agents", headers=_headers(key), json=payload, timeout=60)
    except requests.RequestException as exc:
        return {"ok": False, "error": "cursor_network", "message": str(exc)}
    if created.status_code >= 400:
        return {"ok": False, "error": "cursor_create_failed", "message": _error_body(created)}

    body = created.json()
    agent = body.get("agent") or body
    run = body.get("run") or {}
    agent_id = agent.get("id") or ""
    run_id = run.get("id") or agent.get("latestRunId") or ""
    if not agent_id or not run_id:
        return {
            "ok": False,
            "error": "cursor_bad_response",
            "message": f"创建成功但没有 agent/run id：{str(body)[:200]}",
        }

    deadline = time.monotonic() + TIMEOUT_S
    last: dict[str, Any] = run
    while time.monotonic() < deadline:
        status = (last.get("status") or "").upper()
        if status in {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}:
            break
        time.sleep(POLL_S)
        try:
            polled = requests.get(
                f"{API}/agents/{agent_id}/runs/{run_id}",
                headers=_headers(key),
                timeout=30,
            )
        except requests.RequestException as exc:
            return {
                "ok": False,
                "error": "cursor_poll_failed",
                "message": str(exc),
                "agent_id": agent_id,
                "run_id": run_id,
            }
        if polled.status_code >= 400:
            return {
                "ok": False,
                "error": "cursor_poll_failed",
                "message": _error_body(polled),
                "agent_id": agent_id,
                "run_id": run_id,
            }
        last = polled.json()

    status = (last.get("status") or "").upper()
    text = (last.get("result") or last.get("text") or "").strip()
    pr_url = ""
    branch = ""
    git = last.get("git") or {}
    for b in git.get("branches") or []:
        if isinstance(b, dict):
            pr_url = pr_url or (b.get("prUrl") or b.get("pr_url") or "")
            branch = branch or (b.get("branch") or "")
    ok = status == "FINISHED"
    out: dict[str, Any] = {
        "ok": ok,
        "status": status.lower() or "unknown",
        "runtime": "cloud",
        "agent_id": agent_id,
        "run_id": run_id,
        "friction_id": fid,
        "summary": text[:1200],
        "url": f"https://cursor.com/agents/{agent_id}",
    }
    if pr_url:
        out["pr_url"] = pr_url
    if branch:
        out["branch"] = branch
    if ok:
        friction.resolve(fid)
        out["resolved"] = True
        out["say"] = f"改好了。" + (f" PR：{pr_url}" if pr_url else f" 看进度：{out['url']}")
    else:
        out["say"] = f"Cursor 没改成（{status or '超时'}）。" + (
            f" 看：{out['url']}" if agent_id else ""
        )
    return out
