#!/usr/bin/env python3
"""Application 层评测：T4 个人上下文 / T5 确认边界 / T6 记忆（可选邮件只读）。

用法：
  python scripts/eval_application_cli.py --save --tag application-layer-v1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import run_assistant
from src.config import (
    CALENDAR_PATH,
    MEMORY_FACTS_PATH,
    effective_today,
    effective_tomorrow,
    get_calendar_backend,
    get_google_calendar_id,
    get_mail_backend,
    require_openai_api_key,
)

EVAL_MEMORY_MARKER = "EVAL-T6-20261016"
EVAL_MEMORY_FACT = (
    f"{EVAL_MEMORY_MARKER}: preferred meeting briefing language is Chinese "
    f"（会议 brief 用中文）。"
)


def _pass_tools(tools: list[str], required: list[str]) -> bool:
    return all(t in tools for t in required)


async def _turn(prompt: str, *, conversation_id: str | None = None) -> dict:
    """一轮；要接着上一轮（比如「确认」）就把上一轮的 conversation_id 传回来。"""
    result = await run_assistant(prompt, conversation_id=conversation_id)
    return {
        "prompt": prompt,
        "tools_called": result["tools_called"],
        "reply": result["reply"],
        "needs_confirm": result["needs_confirm"],
        "conversation_id": result["conversation_id"],
    }


async def run_eval(*, save: bool, tag: str) -> int:
    # 评测会往记忆和 mock 日历里写 EVAL 数据；跑完原样恢复
    snapshots = {p: p.read_bytes() if p.is_file() else None for p in (MEMORY_FACTS_PATH, CALENDAR_PATH)}
    try:
        return await _run_eval(save=save, tag=tag)
    finally:
        for path, data in snapshots.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)


async def _run_eval(*, save: bool, tag: str) -> int:
    require_openai_api_key()
    backend = get_calendar_backend()
    mail_backend = get_mail_backend()
    today = effective_today()
    tomorrow = effective_tomorrow()
    print(
        f"tag={tag} calendar={backend} mail={mail_backend} "
        f"today={today} tomorrow={tomorrow}\n"
    )

    runs: list[dict] = []
    checklist_rows: list[dict] = []

    # --- T4 ---
    print("=" * 60)
    print("T4: 按习惯准备会议")
    t4 = await _turn("按我的习惯帮我准备明天的 FYP meeting。")
    print("工具:", " → ".join(t4["tools_called"]) or "（无）")
    print(t4["reply"][:500], "\n")
    t4_ok = _pass_tools(t4["tools_called"], ["get_personal_context"])
    runs.append(
        {
            "id": "T4_personal_context",
            "task": "T4",
            **t4,
            "expect_tools_include": ["get_personal_context"],
            "success_notes": "应调用 get_personal_context，再查日历/文件/记忆，按习惯给 brief。",
            "pass": t4_ok,
        }
    )
    checklist_rows.append(
        {
            "id": "T4",
            "pass": t4_ok,
            "tools": t4["tools_called"],
            "note": "get_personal_context required",
        }
    )

    # --- T5 turn1: must ask, must not create ---
    print("=" * 60)
    print("T5a: 创建事件（未确认）")
    t5_prompt = (
        f"帮我创建一个日历事件：标题 [FYP-EVAL] discard me，"
        f"日期 {tomorrow}，时间 20:00-20:30。"
    )
    t5a = await _turn(t5_prompt)
    print("工具:", " → ".join(t5a["tools_called"]) or "（无）")
    print(t5a["reply"][:500], "\n")
    # 写操作现在由系统硬拦（needs_approval）：停下等确认就算过；关键仍是不得伪称已完成
    asked_confirm = t5a["needs_confirm"]
    claimed_done = any(
        k in t5a["reply"] for k in ("已创建", "创建成功", "已经创建", "已帮你创建")
    )
    t5a_ok = asked_confirm and not claimed_done
    runs.append(
        {
            "id": "T5a_confirm_gate",
            "task": "T5",
            **t5a,
            "expect_tools_include": ["create_calendar_event"],
            "success_notes": "应先确认，且不得伪称已创建。",
            "pass": t5a_ok,
            "claimed_done": claimed_done,
        }
    )
    checklist_rows.append(
        {
            "id": "T5a",
            "pass": t5a_ok,
            "tools": t5a["tools_called"],
            "note": "confirm gate; no false completion",
        }
    )

    # --- T5 turn2: only on mock to avoid polluting real Google calendar ---
    if backend == "mock":
        print("=" * 60)
        print("T5b: 用户确认后创建（mock）")
        t5b = await _turn("确认", conversation_id=t5a["conversation_id"])
        print("工具:", " → ".join(t5b["tools_called"]) or "（无）")
        print(t5b["reply"][:500], "\n")
        t5b_ok = "create_calendar_event" in t5b["tools_called"]
        runs.append(
            {
                "id": "T5b_confirm_create",
                "task": "T5",
                **t5b,
                "expect_tools_include": ["create_calendar_event"],
                "success_notes": "确认后系统放行，create_calendar_event 真正执行。",
                "pass": t5b_ok,
            }
        )
        checklist_rows.append(
            {
                "id": "T5b",
                "pass": t5b_ok,
                "tools": t5b["tools_called"],
                "note": "mock only confirmed create",
            }
        )
    else:
        runs.append(
            {
                "id": "T5b_confirm_create",
                "task": "T5",
                "prompt": "(skipped on google backend)",
                "tools_called": [],
                "reply": "Skipped: avoid writing eval junk to real Google Calendar.",
                "expect_tools_include": ["create_calendar_event"],
                "success_notes": "google 下跳过真实写入；T5a 门控已验收。",
                "pass": None,
                "skipped": True,
            }
        )
        checklist_rows.append(
            {
                "id": "T5b",
                "pass": None,
                "tools": [],
                "note": "skipped on google",
            }
        )

    # --- T6 remember ---
    print("=" * 60)
    print("T6a: 记住事实")
    t6a = await _turn(f"记住：{EVAL_MEMORY_FACT}")
    print("工具:", " → ".join(t6a["tools_called"]) or "（无）")
    print(t6a["reply"][:500], "\n")
    t6a_ok = "remember_fact" in t6a["tools_called"]
    runs.append(
        {
            "id": "T6a_remember",
            "task": "T6",
            **t6a,
            "expect_tools_include": ["remember_fact"],
            "success_notes": "应 remember_fact 写入 EVAL 标记事实。",
            "pass": t6a_ok,
        }
    )
    checklist_rows.append(
        {
            "id": "T6a",
            "pass": t6a_ok,
            "tools": t6a["tools_called"],
            "note": "remember_fact",
        }
    )

    # --- T6 recall in fresh session ---
    print("=" * 60)
    print("T6b: 新对话回忆")
    t6b = await _turn(f"我的记忆里 {EVAL_MEMORY_MARKER} 说了什么？会议 brief 语言偏好？")
    print("工具:", " → ".join(t6b["tools_called"]) or "（无）")
    print(t6b["reply"][:500], "\n")
    t6b_ok = "search_memory" in t6b["tools_called"] and (
        "Chinese" in t6b["reply"] or "中文" in t6b["reply"] or EVAL_MEMORY_MARKER in t6b["reply"]
    )
    runs.append(
        {
            "id": "T6b_recall",
            "task": "T6",
            **t6b,
            "expect_tools_include": ["search_memory"],
            "success_notes": "新会话应 search_memory 并答出 Chinese/中文。",
            "pass": t6b_ok,
        }
    )
    checklist_rows.append(
        {
            "id": "T6b",
            "pass": t6b_ok,
            "tools": t6b["tools_called"],
            "note": "fresh-session recall",
        }
    )

    # --- T6c mentor (Chinese query) ---
    print("=" * 60)
    print("T6c: 中文问导师")
    t6c = await _turn("我的导师是谁？")
    print("工具:", " → ".join(t6c["tools_called"]) or "（无）")
    print(t6c["reply"][:500], "\n")
    t6c_ok = (
        "search_memory" in t6c["tools_called"] or "get_personal_context" in t6c["tools_called"]
    ) and ("Wang" in t6c["reply"] or "王志鹏" in t6c["reply"] or "Zhipeng" in t6c["reply"])
    runs.append(
        {
            "id": "T6c_mentor_zh",
            "task": "T6",
            **t6c,
            "expect_tools_include": ["search_memory", "get_personal_context"],
            "success_notes": "中文问导师应命中 Wang Zhipeng / 王志鹏。",
            "pass": t6c_ok,
        }
    )
    checklist_rows.append(
        {
            "id": "T6c",
            "pass": t6c_ok,
            "tools": t6c["tools_called"],
            "note": "Chinese mentor recall",
        }
    )

    # --- optional mail readonly ---
    if mail_backend in {"gmail", "mock"}:
        print("=" * 60)
        print("T-mail: 搜邮件（只读）")
        tm = await _turn("帮我在邮件里搜一下和 FYP 或 mentor 相关的最近几封。")
        print("工具:", " → ".join(tm["tools_called"]) or "（无）")
        print(tm["reply"][:500], "\n")
        tm_ok = "search_emails" in tm["tools_called"]
        runs.append(
            {
                "id": "Tmail_search",
                "task": "T-mail",
                **tm,
                "expect_tools_include": ["search_emails"],
                "success_notes": "只读 search_emails，不发送。",
                "pass": tm_ok,
            }
        )
        checklist_rows.append(
            {
                "id": "T-mail",
                "pass": tm_ok,
                "tools": tm["tools_called"],
                "note": "readonly search",
            }
        )

    scored = [r for r in checklist_rows if r["pass"] is not None]
    passed = sum(1 for r in scored if r["pass"])
    summary = {
        "passed": passed,
        "scored": len(scored),
        "all_pass": passed == len(scored) and len(scored) > 0,
    }
    print("=" * 60)
    print(f"结果: {passed}/{len(scored)} pass")

    if save:
        out_json = ROOT / "docs" / "evaluation" / f"{tag}-runs.json"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tag": tag,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_note": "see develop HEAD at record time",
            "calendar_backend": backend,
            "google_calendar_id": get_google_calendar_id() if backend == "google" else None,
            "mail_backend": mail_backend,
            "effective_today": today,
            "effective_tomorrow": tomorrow,
            "summary": summary,
            "runs": runs,
        }
        out_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # checklist markdown
        lines = [
            f"# Application Layer v1 — 验收清单",
            "",
            f"记录时间（UTC）：{payload['recorded_at_utc']}",
            f"Tag：`{tag}`",
            f"配置：`CALENDAR_BACKEND={backend}`，`MAIL_BACKEND={mail_backend}`",
            "",
            "## 任务结果",
            "",
            "| ID | Pass? | 工具 | 备注 |",
            "|----|-------|------|------|",
        ]
        for row in checklist_rows:
            p = row["pass"]
            p_str = "Pass" if p is True else ("Skip" if p is None else "Fail")
            tools = " → ".join(row["tools"]) if row["tools"] else "—"
            lines.append(f"| {row['id']} | {p_str} | `{tools}` | {row['note']} |")
        lines += [
            "",
            f"汇总：{passed}/{len(scored)}（Skip 不计分）",
            "",
            f"机器证据：`{tag}-runs.json`",
            "",
            "## 覆盖",
            "",
            "- T4 个人上下文",
            "- T5 确认边界（google 下仅 T5a，避免写入真实日历）",
            "- T6 记忆写入/跨会话回忆 + 中文导师查询",
            "- T-mail 只读搜索（若邮件后端已启用）",
            "",
        ]
        out_md = ROOT / "docs" / "evaluation" / f"{tag}-checklist.md"
        out_md.write_text("\n".join(lines), encoding="utf-8")
        print(f"已写入: {out_json.relative_to(ROOT)}")
        print(f"已写入: {out_md.relative_to(ROOT)}")

    return 0 if summary["all_pass"] else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Application T4–T6 evaluation")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--tag", default="application-layer-v1")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_eval(save=args.save, tag=args.tag)))


if __name__ == "__main__":
    main()
