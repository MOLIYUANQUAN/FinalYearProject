#!/usr/bin/env python3
"""可选 CLI：按顺序跑三条 Demo（需 OPENAI_API_KEY）。

默认打印到终端；加 --save 时把轨迹写入 docs/evaluation/。
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
    effective_today,
    effective_tomorrow,
    get_calendar_backend,
    get_google_calendar_id,
    require_openai_api_key,
)

DEMOS = [
    {
        "id": "demo1_calendar",
        "prompt": "我明天有什么安排？",
        "expect_tools_include": ["get_calendar_events"],
        "success_notes_mock": "应提到 2026-10-13 的 FYP meeting 等 mock 事件。",
        "success_notes_google": "应列出真实日历事件（含导入课表，若已勾选）。",
    },
    {
        "id": "demo2_proposal",
        "prompt": "找到我的 FYP proposal，告诉我项目在做什么。",
        "expect_tools_include": ["search_files", "read_file"],
        "success_notes_mock": "应基于 data/notes/fyp-proposal.md 概括。",
        "success_notes_google": "应基于 data/notes/fyp-proposal.md 概括。",
    },
    {
        "id": "demo3_meeting_brief",
        "prompt": "帮我准备明天的 FYP meeting。",
        "expect_tools_include": ["get_calendar_events", "search_files", "read_file"],
        "success_notes_mock": "应串联日历与文件，输出 meeting brief。",
        "success_notes_google": "应串联真实日历与本地文件，输出 meeting brief。",
    },
]


async def run_demos(*, save: bool, tag: str) -> int:
    require_openai_api_key()
    backend = get_calendar_backend()
    print(
        f"tag={tag} 日历后端={backend}，今天={effective_today()}，明天={effective_tomorrow()}\n"
    )

    runs: list[dict] = []
    for i, demo in enumerate(DEMOS, 1):
        print("=" * 60)
        print(f"Demo {i}: {demo['prompt']}")
        print("-" * 60)
        result = await run_assistant(demo["prompt"])
        tools = result["tools_called"]
        print("工具:", " → ".join(tools) or "（无）")
        print(result["reply"])
        print()
        note_key = "success_notes_google" if backend == "google" else "success_notes_mock"
        runs.append(
            {
                "id": demo["id"],
                "prompt": demo["prompt"],
                "tools_called": tools,
                "reply": result["reply"],
                "expect_tools_include": demo["expect_tools_include"],
                "success_notes": demo[note_key],
            }
        )

    if save:
        out = ROOT / "docs" / "evaluation" / f"{tag}-runs.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tag": tag,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "calendar_backend": backend,
            "google_calendar_id": get_google_calendar_id() if backend == "google" else None,
            "effective_today": effective_today(),
            "effective_tomorrow": effective_tomorrow(),
            "runs": runs,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已写入证据: {out.relative_to(ROOT)}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Demo 1–3 and optionally save evidence")
    parser.add_argument("--save", action="store_true", help="Save tool trajectories to docs/evaluation/")
    parser.add_argument(
        "--tag",
        default="baseline-v1",
        help="Evidence tag / filename prefix (default: baseline-v1)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_demos(save=args.save, tag=args.tag)))


if __name__ == "__main__":
    main()
