#!/usr/bin/env python3
"""可选 CLI：按顺序跑三条 Baseline Demo（需 OPENAI_API_KEY）。

默认打印到终端；加 --save 时把轨迹写入 docs/evaluation/baseline-v1-runs.json，
供报告 / Evaluation 对照基线使用。
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
from src.config import MOCK_TODAY, MOCK_TOMORROW, require_openai_api_key

DEMOS = [
    {
        "id": "demo1_calendar",
        "prompt": "我明天下午有什么安排？",
        "expect_tools_include": ["get_calendar_events"],
        "success_notes": "应提到 2026-10-13 下午 FYP meeting（14:00、Kilburn Building）。",
    },
    {
        "id": "demo2_proposal",
        "prompt": "找到我的 FYP proposal，告诉我项目在做什么。",
        "expect_tools_include": ["search_files", "read_file"],
        "success_notes": "应基于 data/notes/fyp-proposal.md 概括 Personal AI Assistant / Baseline。",
    },
    {
        "id": "demo3_meeting_brief",
        "prompt": "帮我准备明天的 FYP meeting。",
        "expect_tools_include": ["get_calendar_events", "search_files", "read_file"],
        "success_notes": "应串联日历与文件，输出 meeting brief（时间地点、项目摘要、讨论点）。",
    },
]

EVIDENCE_PATH = ROOT / "docs" / "evaluation" / "baseline-v1-runs.json"


async def run_demos(*, save: bool) -> int:
    require_openai_api_key()
    print(f"演示今天={MOCK_TODAY}，明天={MOCK_TOMORROW}\n")

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
        runs.append(
            {
                "id": demo["id"],
                "prompt": demo["prompt"],
                "tools_called": tools,
                "reply": result["reply"],
                "expect_tools_include": demo["expect_tools_include"],
                "success_notes": demo["success_notes"],
            }
        )

    if save:
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tag": "baseline-v1",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "mock_today": MOCK_TODAY,
            "mock_tomorrow": MOCK_TOMORROW,
            "runs": runs,
        }
        EVIDENCE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"已写入证据: {EVIDENCE_PATH.relative_to(ROOT)}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Baseline Demo 1–3")
    parser.add_argument(
        "--save",
        action="store_true",
        help=f"Save tool trajectories to {EVIDENCE_PATH.relative_to(ROOT)}",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_demos(save=args.save)))


if __name__ == "__main__":
    main()
