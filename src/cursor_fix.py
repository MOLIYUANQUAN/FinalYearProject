"""用 Cursor SDK 按一条产品摩擦改仓库。本机走 local，云上 Fly 走 cloud。"""

from __future__ import annotations

import os
from typing import Any

from src.config import ROOT_DIR, load_env
from src import friction

DEFAULT_REPO = "https://github.com/MOLIYUANQUAN/FinalYearProject.git"
DEFAULT_REF = "develop"
DEFAULT_MODEL = "composer-2.5"


def _api_key() -> str:
    load_env()
    return (os.getenv("CURSOR_API_KEY") or "").strip()


def _runtime() -> str:
    load_env()
    forced = (os.getenv("CURSOR_AGENT_RUNTIME") or "").strip().lower()
    if forced in {"local", "cloud"}:
        return forced
    # Fly 机器上没有可写的本机仓库，默认云上改
    if (os.getenv("FLY_APP_NAME") or "").strip():
        return "cloud"
    return "local"


def _repo_url() -> str:
    return (os.getenv("CURSOR_REPO_URL") or DEFAULT_REPO).strip() or DEFAULT_REPO


def _repo_ref() -> str:
    return (os.getenv("CURSOR_REPO_REF") or DEFAULT_REF).strip() or DEFAULT_REF


def _model() -> str:
    return (os.getenv("CURSOR_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _prompt_for(item: dict[str, Any]) -> str:
    better = (item.get("better") or "").strip()
    better_line = f"\n他希望：{better}" if better else ""
    return f"""你在 Jimmy 的 FYP 仓库里改 Friday 产品代码。

产品摩擦（必须消掉）：
{item.get("what")}{better_line}

约束：
- 只做消掉这条摩擦所需的最小改动；别顺手重构。
- 日常开发分支是 develop；别动 .env、secrets、token。
- 注释和用户可见文案用中文，跟现有风格一致。
- 「需要你」是稀缺打扰面：明天的日历项不要进 attention；标题里已过点的待办不要再催。
- 改完用几句话说明改了哪些文件、如何验收。
"""


def _summarize_result(result: Any, runtime: str) -> dict[str, Any]:
    status = getattr(result, "status", None) or ""
    text = (getattr(result, "result", None) or "").strip()
    agent_id = getattr(result, "agent_id", "") or ""
    run_id = getattr(result, "id", "") or ""
    pr_url = ""
    branch = ""
    git = getattr(result, "git", None)
    if git is not None:
        branches = getattr(git, "branches", None) or []
        if branches:
            first = branches[0]
            pr_url = getattr(first, "pr_url", "") or ""
            branch = getattr(first, "branch", "") or ""
    ok = str(status) in {"finished", "RunResultStatus.FINISHED", "completed"} or status == "finished"
    # status may be enum
    status_s = getattr(status, "value", None) or str(status)
    ok = status_s in {"finished", "completed"}
    out: dict[str, Any] = {
        "ok": ok,
        "status": status_s,
        "runtime": runtime,
        "agent_id": agent_id,
        "run_id": run_id,
        "summary": text[:1200],
    }
    if pr_url:
        out["pr_url"] = pr_url
    if branch:
        out["branch"] = branch
    return out


def run_fix(friction_id: str) -> dict[str, Any]:
    """按 friction id 起一次 Cursor Agent。同步阻塞，可能要几分钟。"""
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

    try:
        from cursor_sdk import Agent, AgentOptions, CloudAgentOptions, CloudRepository, CursorAgentError, LocalAgentOptions
    except ImportError:
        return {
            "ok": False,
            "error": "sdk_missing",
            "message": "缺少 cursor-sdk：在 .venv 里 pip install cursor-sdk。",
        }

    runtime = _runtime()
    prompt = _prompt_for(item)
    model = _model()

    try:
        if runtime == "cloud":
            options = AgentOptions(
                api_key=key,
                model=model,
                cloud=CloudAgentOptions(
                    repos=[CloudRepository(url=_repo_url(), starting_ref=_repo_ref())],
                    auto_create_pr=True,
                    skip_reviewer_request=True,
                ),
            )
        else:
            options = AgentOptions(
                api_key=key,
                model=model,
                local=LocalAgentOptions(cwd=str(ROOT_DIR)),
            )
        result = Agent.prompt(prompt, options)
    except CursorAgentError as err:
        return {
            "ok": False,
            "error": "cursor_startup_failed",
            "message": getattr(err, "message", None) or str(err),
            "retryable": bool(getattr(err, "is_retryable", False)),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "cursor_failed", "message": str(exc)}

    summary = _summarize_result(result, runtime)
    summary["friction_id"] = fid
    if summary.get("ok"):
        friction.resolve(fid)
        summary["resolved"] = True
        if summary.get("pr_url"):
            summary["say"] = f"改好了，PR：{summary['pr_url']}"
        elif runtime == "local":
            summary["say"] = "本机改好了，你看一眼 diff 再提交。"
        else:
            summary["say"] = "云上改完了。" + (f" 摘要：{summary['summary'][:200]}" if summary.get("summary") else "")
    else:
        summary["say"] = f"Cursor 没改成（{summary.get('status')}）。" + (
            f" {summary['summary'][:200]}" if summary.get("summary") else ""
        )
    return summary
