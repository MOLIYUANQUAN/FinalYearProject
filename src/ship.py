"""Cursor 改完后的待部署：在 Friday 里看改了什么，确认后合并 develop 并部署。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import requests

from src.config import DATA_DIR, ROOT_DIR, load_env
from src import friction

PENDING_PATH = DATA_DIR / "feedback" / "pending_ship.json"
GITHUB_API = "https://api.github.com"
DEFAULT_REPO = "MOLIYUANQUAN/FinalYearProject"
DEFAULT_BASE = "develop"


def _repo_slug() -> str:
    load_env()
    url = (os.getenv("CURSOR_REPO_URL") or f"https://github.com/{DEFAULT_REPO}").strip()
    url = url.removesuffix(".git")
    if "github.com/" in url:
        return url.split("github.com/", 1)[1].strip("/")
    return DEFAULT_REPO


def _base() -> str:
    return (os.getenv("CURSOR_REPO_REF") or DEFAULT_BASE).strip() or DEFAULT_BASE


def _gh_headers() -> dict[str, str]:
    load_env()
    headers = {"Accept": "application/vnd.github+json"}
    token = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def compare(branch: str) -> dict[str, Any]:
    """develop...branch 的文件级改动（公开仓可不带 token）。"""
    branch = (branch or "").strip()
    if not branch:
        return {"ok": False, "error": "missing_branch", "message": "没有分支名。"}
    url = f"{GITHUB_API}/repos/{_repo_slug()}/compare/{_base()}...{branch}"
    try:
        res = requests.get(url, headers=_gh_headers(), timeout=30)
    except requests.RequestException as exc:
        return {"ok": False, "error": "network", "message": str(exc)}
    if res.status_code >= 400:
        return {"ok": False, "error": "compare_failed", "message": (res.text or "")[:200]}
    data = res.json()
    files = []
    for f in data.get("files") or []:
        files.append(
            {
                "path": f.get("filename") or "",
                "status": f.get("status") or "",
                "additions": int(f.get("additions") or 0),
                "deletions": int(f.get("deletions") or 0),
            }
        )
    return {
        "ok": True,
        "ahead": int(data.get("ahead_by") or 0),
        "files": files,
        "html_url": data.get("html_url") or "",
        "permalink_url": data.get("permalink_url") or "",
    }


def _format_files(files: list[dict[str, Any]]) -> str:
    if not files:
        return "（还没取到文件列表）"
    lines = []
    for f in files:
        lines.append(f"- {f['path']}（+{f['additions']}/-{f['deletions']}）")
    return "\n".join(lines)


def preview_text(pending: dict[str, Any]) -> str:
    """给用户看的纯文本：改了什么 + 怎么验收 + 确认就部署。"""
    summary = (pending.get("summary") or "").strip()
    files = pending.get("files") or []
    branch = pending.get("branch") or ""
    agent = pending.get("agent_url") or ""
    compare_url = pending.get("compare_url") or ""
    parts = [
        "Cursor 改完了，还没上线。改动如下：",
        "",
        "改动的文件：",
        _format_files(files),
    ]
    if summary:
        parts.extend(["", "说明：", summary[:1500]])
    parts.extend(
        [
            "",
            "效果：合进 develop 并部署后，打开 Friday 点「新对话」看开场卡片。",
            f"分支：{branch}" if branch else "",
            f"对比：{compare_url}" if compare_url else "",
            f"Agent：{agent}" if agent else "",
            "",
            "要上线就点确认（或说「确认部署」）；不要就说取消。",
        ]
    )
    return "\n".join(p for p in parts if p is not None)


def save_pending(
    *,
    branch: str,
    summary: str,
    agent_id: str = "",
    run_id: str = "",
    friction_id: str = "",
    agent_url: str = "",
) -> dict[str, Any]:
    cmp = compare(branch)
    files = cmp.get("files") if cmp.get("ok") else []
    compare_url = (
        cmp.get("html_url")
        or f"https://github.com/{_repo_slug()}/compare/{_base()}...{branch}"
    )
    pending = {
        "branch": branch,
        "base": _base(),
        "summary": (summary or "").strip(),
        "files": files or [],
        "ahead": cmp.get("ahead") if cmp.get("ok") else 0,
        "agent_id": agent_id,
        "run_id": run_id,
        "friction_id": friction_id,
        "agent_url": agent_url or (f"https://cursor.com/agents/{agent_id}" if agent_id else ""),
        "compare_url": compare_url,
    }
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(pending, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending["ok"] = True
    pending["say"] = preview_text(pending)
    return pending


def load_pending() -> dict[str, Any] | None:
    if not PENDING_PATH.is_file():
        return None
    try:
        data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and data.get("branch") else None


def recover_latest_from_cursor() -> dict[str, Any] | None:
    """本机/云上 pending 文件丢了时，从最近一次 friday-friction Agent 找回分支。"""
    load_env()
    key = (os.getenv("CURSOR_API_KEY") or "").strip()
    if not key:
        return None
    try:
        res = requests.get(
            "https://api.cursor.com/v1/agents",
            headers={"Authorization": f"Bearer {key}"},
            params={"limit": 10},
            timeout=30,
        )
    except requests.RequestException:
        return None
    if res.status_code >= 400:
        return None
    for agent in res.json().get("items") or []:
        name = agent.get("name") or ""
        if not str(name).startswith("friday-friction"):
            continue
        aid = agent.get("id") or ""
        rid = agent.get("latestRunId") or ""
        if not aid or not rid:
            continue
        run = requests.get(
            f"https://api.cursor.com/v1/agents/{aid}/runs/{rid}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        if run.status_code >= 400:
            continue
        body = run.json()
        if (body.get("status") or "").upper() != "FINISHED":
            continue
        branch = ""
        for b in (body.get("git") or {}).get("branches") or []:
            if isinstance(b, dict) and b.get("branch"):
                branch = b["branch"]
                break
        if not branch:
            continue
        return save_pending(
            branch=branch,
            summary=(body.get("result") or body.get("text") or "")[:2000],
            agent_id=aid,
            run_id=rid,
            agent_url=f"https://cursor.com/agents/{aid}",
        )
    return None


def load_or_recover_pending() -> dict[str, Any] | None:
    return load_pending() or recover_latest_from_cursor()


def clear_pending() -> None:
    if PENDING_PATH.is_file():
        PENDING_PATH.unlink()


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def _merge_local(branch: str) -> dict[str, Any]:
    if not (ROOT_DIR / ".git").is_dir():
        return {"ok": False, "error": "no_git", "message": "这台机器上没有 git 仓库。"}
    fetch = _run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "fetch", "origin", branch])
    if fetch.returncode != 0:
        return {"ok": False, "error": "fetch_failed", "message": (fetch.stderr or fetch.stdout)[:300]}
    # 在 develop 上合并
    _run(["git", "checkout", _base()])
    merge = _run(["git", "merge", f"origin/{branch}", "-m", f"Ship Cursor fix from {branch}"])
    if merge.returncode != 0:
        _run(["git", "merge", "--abort"])
        return {"ok": False, "error": "merge_failed", "message": (merge.stderr or merge.stdout)[:300]}
    push = _run(["git", "-c", "http.proxy=", "-c", "https.proxy=", "push", "origin", _base()])
    if push.returncode != 0:
        return {"ok": False, "error": "push_failed", "message": (push.stderr or push.stdout)[:300]}
    return {"ok": True, "method": "local_git"}


def _merge_github(branch: str) -> dict[str, Any]:
    load_env()
    token = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    if not token:
        return {
            "ok": False,
            "error": "missing_github_token",
            "message": "云上合并需要 GITHUB_TOKEN。本机有仓库时可直接合并。",
        }
    # 开 PR 再 merge（已有 PR 也无所谓）
    slug = _repo_slug()
    headers = _gh_headers()
    pr = requests.post(
        f"{GITHUB_API}/repos/{slug}/pulls",
        headers=headers,
        json={"title": f"Ship {branch}", "head": branch, "base": _base(), "body": "Friday 确认部署"},
        timeout=30,
    )
    if pr.status_code == 422:
        # 可能已有 PR：列出 head
        listed = requests.get(
            f"{GITHUB_API}/repos/{slug}/pulls",
            headers=headers,
            params={"head": f"{slug.split('/')[0]}:{branch}", "state": "open"},
            timeout=30,
        )
        items = listed.json() if listed.ok else []
        if not items:
            return {"ok": False, "error": "pr_failed", "message": (pr.text or "")[:200]}
        number = items[0]["number"]
    elif pr.status_code >= 400:
        return {"ok": False, "error": "pr_failed", "message": (pr.text or "")[:200]}
    else:
        number = pr.json()["number"]
    merged = requests.put(
        f"{GITHUB_API}/repos/{slug}/pulls/{number}/merge",
        headers=headers,
        json={"merge_method": "merge", "commit_title": f"Ship {branch}"},
        timeout=30,
    )
    if merged.status_code >= 400:
        return {"ok": False, "error": "merge_failed", "message": (merged.text or "")[:200]}
    return {"ok": True, "method": "github_api", "pr": number}


def _deploy() -> dict[str, Any]:
    script = ROOT_DIR / "scripts" / "deploy_fly.py"
    py = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(os.environ.get("PYTHON", "") or "python")
    if not script.is_file():
        return {"ok": False, "error": "no_deploy_script", "message": "找不到 deploy_fly.py。"}
    proc = subprocess.run(
        [str(py), str(script)],
        cwd=ROOT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": "deploy_failed",
            "message": ((proc.stderr or "") + (proc.stdout or ""))[-400:],
        }
    return {"ok": True, "log_tail": (proc.stdout or "")[-300:]}


def ship(*, user_confirmed: bool) -> dict[str, Any]:
    if not user_confirmed:
        pending = load_pending()
        return {
            "ok": False,
            "error": "user_not_confirmed",
            "message": "还没确认。请先 request_user_confirmation，说明要合并并部署到云上。",
            "preview": preview_text(pending) if pending else "",
        }
    pending = load_or_recover_pending()
    if not pending:
        return {"ok": False, "error": "nothing_pending", "message": "没有待部署的 Cursor 改动。"}
    branch = pending["branch"]
    merged = _merge_local(branch)
    if not merged.get("ok"):
        merged = _merge_github(branch)
    if not merged.get("ok"):
        return merged
    deployed = _deploy()
    fid = (pending.get("friction_id") or "").strip()
    if fid:
        friction.resolve(fid)
    clear_pending()
    if not deployed.get("ok"):
        return {
            "ok": True,
            "merged": True,
            "deployed": False,
            "method": merged.get("method"),
            "say": (
                f"代码已合进 {_base()}，但自动部署失败：{deployed.get('message', '')}。"
                "本机可跑 scripts/deploy_fly.py。"
            ),
        }
    return {
        "ok": True,
        "merged": True,
        "deployed": True,
        "method": merged.get("method"),
        "say": "已合进 develop 并部署到云上。刷新页面，点「新对话」看效果。",
    }
