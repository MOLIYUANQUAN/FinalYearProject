"""用 Cursor Cloud Agents API 按一条产品摩擦改仓库。

Windows 上 cursor-sdk 的本机 bridge 会踩 WinError 10038，所以默认走
https://api.cursor.com/v1/agents（纯 HTTP），不依赖本机 bridge。

确认后只创建 Agent 就立刻返回；轮询在后台线程做。连接断了也不丢活——
下一轮对话会 refresh_job 把结果收回来。
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests

from src import friction, ship
from src.config import FEEDBACK_DIR, load_env

DEFAULT_REPO = "https://github.com/MOLIYUANQUAN/FinalYearProject"
DEFAULT_REF = "develop"
DEFAULT_MODEL = "composer-2.5"
API = "https://api.cursor.com/v1"
POLL_S = 5
TIMEOUT_S = 20 * 60
JOB_PATH = FEEDBACK_DIR / "cursor_job.json"

_lock = threading.Lock()
_bg_started_for: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    return f"""你在 Zeep 的 FYP 仓库里改 Friday 产品代码。

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


def _load_job() -> dict[str, Any] | None:
    if not JOB_PATH.is_file():
        return None
    try:
        data = json.loads(JOB_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and data.get("agent_id") else None


def _save_job(job: dict[str, Any]) -> None:
    JOB_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOB_PATH.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _clear_job() -> None:
    if JOB_PATH.is_file():
        try:
            JOB_PATH.unlink()
        except OSError:
            pass


def _fetch_run(key: str, agent_id: str, run_id: str) -> dict[str, Any]:
    res = requests.get(
        f"{API}/agents/{agent_id}/runs/{run_id}",
        headers=_headers(key),
        timeout=30,
    )
    if res.status_code >= 400:
        raise RuntimeError(_error_body(res))
    return res.json()


def _finalize(last: dict[str, Any], *, agent_id: str, run_id: str, friction_id: str) -> dict[str, Any]:
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
    url = f"https://cursor.com/agents/{agent_id}"
    out: dict[str, Any] = {
        "ok": ok,
        "status": status.lower() or "unknown",
        "runtime": "cloud",
        "agent_id": agent_id,
        "run_id": run_id,
        "friction_id": friction_id,
        "summary": text[:1200],
        "url": url,
    }
    if pr_url:
        out["pr_url"] = pr_url
    if branch:
        out["branch"] = branch
    if ok and branch:
        pending = ship.save_pending(
            branch=branch,
            summary=text,
            agent_id=agent_id,
            run_id=run_id,
            friction_id=friction_id,
            agent_url=url,
        )
        out["say"] = pending.get("say") or text[:800]
        out["pending_ship"] = True
        out["files"] = pending.get("files") or []
    elif ok:
        out["say"] = (text[:800] or "改完了，但没有分支名，没法自动部署。") + f" 看：{url}"
    else:
        out["say"] = f"Cursor 没改成（{status or '超时'}）。" + (f" 看：{url}" if agent_id else "")
    return out


def _bg_poll(agent_id: str, run_id: str, friction_id: str) -> None:
    global _bg_started_for
    key = _api_key()
    if not key:
        return
    deadline = time.monotonic() + TIMEOUT_S
    last: dict[str, Any] = {}
    try:
        while time.monotonic() < deadline:
            try:
                last = _fetch_run(key, agent_id, run_id)
            except Exception as exc:  # noqa: BLE001
                with _lock:
                    job = _load_job() or {}
                    job.update(
                        {
                            "status": "error",
                            "error": str(exc)[:300],
                            "updated_at": _now(),
                        }
                    )
                    _save_job(job)
                return
            status = (last.get("status") or "").upper()
            with _lock:
                job = _load_job() or {}
                if job.get("agent_id") != agent_id:
                    return
                job["run_status"] = status.lower()
                job["updated_at"] = _now()
                _save_job(job)
            if status in {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}:
                out = _finalize(last, agent_id=agent_id, run_id=run_id, friction_id=friction_id)
                with _lock:
                    job = _load_job() or {}
                    if job.get("agent_id") != agent_id:
                        return
                    job.update(
                        {
                            "status": "done" if out.get("ok") else "failed",
                            "run_status": out.get("status"),
                            "result": out,
                            "updated_at": _now(),
                        }
                    )
                    _save_job(job)
                return
            time.sleep(POLL_S)
        with _lock:
            job = _load_job() or {}
            if job.get("agent_id") == agent_id:
                job.update({"status": "failed", "error": "timeout", "updated_at": _now()})
                _save_job(job)
    finally:
        with _lock:
            if _bg_started_for == f"{agent_id}:{run_id}":
                _bg_started_for = None


def _ensure_bg(job: dict[str, Any]) -> None:
    global _bg_started_for
    if (job.get("status") or "") != "running":
        return
    agent_id = job.get("agent_id") or ""
    run_id = job.get("run_id") or ""
    if not agent_id or not run_id:
        return
    key = f"{agent_id}:{run_id}"
    with _lock:
        if _bg_started_for == key:
            return
        _bg_started_for = key
    threading.Thread(
        target=_bg_poll,
        args=(agent_id, run_id, job.get("friction_id") or ""),
        daemon=True,
        name=f"cursor-poll-{agent_id[:8]}",
    ).start()


def refresh_job() -> dict[str, Any] | None:
    """每轮对话前调用：接上后台结果；进程重启后也能靠 agent_id 收回来。"""
    with _lock:
        job = _load_job()
    if not job:
        return None
    status = job.get("status") or ""
    if status in {"done", "failed", "error"}:
        return job
    if status != "running":
        return job

    key = _api_key()
    agent_id = job.get("agent_id") or ""
    run_id = job.get("run_id") or ""
    if not key or not agent_id or not run_id:
        return job

    try:
        last = _fetch_run(key, agent_id, run_id)
    except Exception:  # noqa: BLE001
        _ensure_bg(job)
        return job

    run_status = (last.get("status") or "").upper()
    if run_status in {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}:
        out = _finalize(
            last,
            agent_id=agent_id,
            run_id=run_id,
            friction_id=job.get("friction_id") or "",
        )
        with _lock:
            job = _load_job() or job
            job.update(
                {
                    "status": "done" if out.get("ok") else "failed",
                    "run_status": out.get("status"),
                    "result": out,
                    "updated_at": _now(),
                }
            )
            _save_job(job)
        return job

    with _lock:
        job = _load_job() or job
        job["run_status"] = run_status.lower()
        job["updated_at"] = _now()
        _save_job(job)
    _ensure_bg(job)
    return job


def chat_block() -> str:
    """注入每轮上下文：Cursor 在改 / 改完待部署。"""
    job = refresh_job()
    pending = ship.load_pending()
    if pending and pending.get("branch"):
        files = pending.get("files") or []
        n = len(files)
        return (
            "Cursor 改完了，有一版待部署（还没上线）。"
            f"改了约 {n} 个文件，分支 {pending.get('branch')}。"
            "他若问起或你刚发现：立刻 preview_pending_ship，把 say 原样给他，再问要不要部署。"
            "不要装作不知道。"
        )
    if not job:
        return ""
    status = job.get("status") or ""
    url = job.get("url") or ""
    if status == "running":
        return (
            "Cursor 正在改代码（后台跑着）。他问进度就说还在改、好了会告诉他；"
            "不要再开一个新的 Cursor 任务，除非他明确说重做。"
            + (f" 进度页：{url}" if url else "")
        )
    if status == "done":
        result = job.get("result") or {}
        say = (result.get("say") or "").strip()
        if say:
            return (
                "Cursor 刚改完。把下面说明原样给他（或先 preview_pending_ship），再问要不要部署：\n"
                + say[:1200]
            )
        return "Cursor 刚改完。立刻 preview_pending_ship，把 say 原样给他。"
    if status in {"failed", "error"}:
        err = job.get("error") or (job.get("result") or {}).get("say") or "失败"
        return f"最近一次 Cursor 改代码没成功：{err}。他问起就直说；要重做需再确认一次。"
    return ""


def start_fix(friction_id: str) -> dict[str, Any]:
    """创建云上 Agent 后立刻返回；轮询进后台。"""
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

    with _lock:
        existing = _load_job()
    if existing and (existing.get("status") or "") == "running":
        return {
            "ok": True,
            "started": False,
            "status": "running",
            "agent_id": existing.get("agent_id"),
            "run_id": existing.get("run_id"),
            "url": existing.get("url"),
            "say": (
                "已经有一个 Cursor 任务在跑了，不用再开一个。"
                "做好了你问「改了什么」；也可以走开，下一轮我会告诉你。"
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

    url = f"https://cursor.com/agents/{agent_id}"
    job = {
        "status": "running",
        "agent_id": agent_id,
        "run_id": run_id,
        "friction_id": fid,
        "url": url,
        "what": item.get("what") or "",
        "started_at": _now(),
        "updated_at": _now(),
    }
    with _lock:
        _save_job(job)
    _ensure_bg(job)

    return {
        "ok": True,
        "started": True,
        "status": "running",
        "agent_id": agent_id,
        "run_id": run_id,
        "friction_id": fid,
        "url": url,
        "say": (
            "已经交给 Cursor 了，大概一两分钟。"
            "你可以走开；做好了问我「改了什么」，或再说一句我就会告诉你。"
            "不必一直盯着这个页面。"
        ),
    }


def check_status() -> dict[str, Any]:
    """他问「改好了吗」时用。会先 refresh。"""
    job = refresh_job()
    pending = ship.load_or_recover_pending()
    if pending and pending.get("branch"):
        refreshed = ship.save_pending(
            branch=pending["branch"],
            summary=pending.get("summary") or "",
            agent_id=pending.get("agent_id") or "",
            run_id=pending.get("run_id") or "",
            friction_id=pending.get("friction_id") or "",
            agent_url=pending.get("agent_url") or "",
        )
        return {
            "ok": True,
            "status": "ready",
            "pending_ship": True,
            "say": refreshed["say"],
            "files": refreshed.get("files") or [],
        }
    if not job:
        return {"ok": True, "status": "idle", "say": "现在没有进行中的 Cursor 任务，也没有待部署的改动。"}
    status = job.get("status") or "unknown"
    if status == "running":
        return {
            "ok": True,
            "status": "running",
            "url": job.get("url"),
            "say": "还在改，好了会进待部署。你可以问「改了什么」或稍后再问。",
        }
    if status == "done":
        result = job.get("result") or {}
        return {
            "ok": True,
            "status": "done",
            "say": result.get("say")
            or "改完了。请 preview_pending_ship 看详情，或说「确认部署」。",
            "result": result,
        }
    return {
        "ok": False,
        "status": status,
        "say": (job.get("result") or {}).get("say")
        or job.get("error")
        or "最近一次 Cursor 没成功。",
        "url": job.get("url"),
    }


def acknowledge_delivered() -> None:
    """结果已经告诉用户后，清掉 done 状态，避免每轮重复念。pending_ship 仍保留。"""
    with _lock:
        job = _load_job()
        if job and (job.get("status") or "") in {"done", "failed", "error"}:
            _clear_job()
